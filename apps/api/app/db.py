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


async def arm_request(db, *, user_id: str) -> None:
    """Bind the current transaction to the least-privilege app role + caller claims.

    Why this exists (audit finding): the dev compose DSN is the `postgres`
    superuser. Superusers bypass RLS even with FORCE ROW LEVEL SECURITY, so every
    app query was reading across tenants while the tests (which explicitly
    `SET LOCAL ROLE lexsim_app`) passed. This helper makes the running app do the
    same thing the tests do, and fails closed if the effective role can bypass RLS.

    Transaction-local by design: callers that commit per turn (debate/audit
    durability) must call this again after each commit.
    """
    s = get_settings()
    role = s.db_app_role
    if role:
        # Validated by Settings.validate_provider(); identifiers cannot be bound.
        await db.execute(text(f"SET LOCAL ROLE {role}"))
    await db.execute(text("SET LOCAL search_path = public, auth"))
    await db.execute(
        text("SELECT set_config('request.jwt.claims', :claims, true)"),
        {"claims": f'{{"sub": "{user_id}", "role": "authenticated"}}'},
    )
    if s.db_require_non_superuser:
        bypass = (
            await db.execute(
                text(
                    "SELECT rolsuper OR rolbypassrls FROM pg_roles"
                    " WHERE rolname = current_user"
                )
            )
        ).scalar_one_or_none()
        if bypass is not False:
            raise RuntimeError(
                "refusing to run as a superuser/BYPASSRLS role — RLS would be bypassed;"
                " configure DB_APP_ROLE (member of lexsim_app) or set"
                " DB_REQUIRE_NON_SUPERUSER=false only for controlled migrations"
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

    COMPLIANCE NOTE (RFC 6750 §2.3 / RFC 9700 §4.3.2, updated): LEGACY — the FE now
    uses fetch+ReadableStream with the Authorization header (Phase-2 item ③, done);
    this fallback is kept for exactly one release window and must NOT reach prod
    (tokens in URLs leak to browser history, proxies, access logs; TokenScrubFilter
    is the interim mitigation, not the fix). Removal is tracked by
    tests/test_sse_auth_surface.py::test_openapi_token_param_is_query_optional_not_required.
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
        # Bind the least-privilege role + verified claims before any query. Also
        # pins schema resolution: dev GoTrue once put `auth` first on the role
        # search_path, silently resolving unqualified `users`/`cases` wrongly.
        await arm_request(session, user_id=sub)
        # Verified claims on the session info dict — routers use these for the
        # auth.users -> users mirror upsert (never client-supplied values).
        session.info["user_sub"] = sub
        session.info["user_email"] = email
        yield session