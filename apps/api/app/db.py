"""Async engine + session factory.

RLS (SECURITY_CHECKLIST S2): the caller's Supabase JWT is forwarded to Postgres
per session so `auth.uid()` resolves inside RLS policies. Tenant isolation is
enforced by RLS on all six tenant tables — never bypass with the service key.

SECURITY (verified 30 Aug): the JWT bypass guard below is deliberate. RLS
policies alone do NOT protect a connection that presented superuser/service
credentials — any call path that reaches Postgres without a verified Bearer
token would run with RLS bypassed. Fail closed: no verified token -> no session.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import jwt  # pyjwt
from fastapi import Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=20)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


def decode_supabase_jwt(token: str) -> dict:
    """Verify signature + exp against the GoTrue/Supabase secret. Raises on forgery.

    NOTE: self-hosted GoTrue v2.196 issues `aud: ""` on access tokens (verified live);
    hosted Supabase sets `aud: "authenticated"`. Accept either — the signature check
    against the shared secret is the security boundary; the audience filter is not.

    COMPLIANCE/ROOT-CAUSE (30 Aug, aud fix verified live): passing audience="authenticated"
    makes pyjwt raise MissingRequiredClaimError("aud") for aud:"" tokens — and that
    exception is NOT a subclass of InvalidAudienceError in this pyjwt, so the old
    except-InvalidAudienceError fallback could never fire. Single-call form below
    verifies signature + exp + sub but not aud; forged-secret tokens still rejected
    (test_rls / probe: wrong-key token -> InvalidSignature/DecodeError).
    """
    return jwt.decode(
        token,
        settings.supabase_jwt_secret,
        algorithms=["HS256"],
        options={"require": ["exp", "sub"], "verify_aud": False},
    )


async def get_db(
    authorization: str | None = Header(default=None, alias="Authorization"),
    token: str | None = None,  # SSE-only query-param fallback (?token=…)
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session whose request.jwt.claims carry the VERIFIED caller's claims.

    SECURITY: the claims string is built ONLY from the cryptographically verified
    payload — never from a client-supplied blob. Requests without a valid Bearer
    token get NO session at all (fail closed).

    ?token= fallback (S4-audit item): EventSource cannot send headers, so the SSE
    debate endpoint supplies the same JWT as a query param. Rules (security):
    identical decode path (same HMAC signature check, no looser SSE rules), and the
    token value is never logged — it is consumed here and discarded.
    """
    raw = None
    if authorization and authorization.startswith("Bearer "):
        raw = authorization.removeprefix("Bearer ")
    elif token:
        raw = token  # EventSource-only surface, identical verification below
    if not raw:
        raise HTTPException(status_code=401, detail="missing or malformed Authorization header")
    try:
        claims = decode_supabase_jwt(raw)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from None
    sub = claims["sub"]
    email = claims.get("email") or f"{sub}@unknown.local"
    async with SessionFactory() as session:
        await session.execute(
            text("SELECT set_config('request.jwt.claims', :claims, true)"),
            {"claims": f'{{"sub": "{sub}", "role": "authenticated"}}'},
        )
        # Verified claims on the session info dict — routers use these for the
        # auth.users -> users mirror upsert (never client-supplied values).
        session.info["user_sub"] = sub
        session.info["user_email"] = email
        yield session