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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()
engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=20)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

# Nothing in the app is exempt: every DB-touching request must present a valid token.
_AUDIT_WRITER_CLAIMS = '{"role": "authenticated"}'


def decode_supabase_jwt(token: str) -> dict:
    """Verify signature + exp against the GoTrue/Supabase secret. Raises on forgery."""
    return jwt.decode(
        token,
        settings.supabase_jwt_secret,
        algorithms=["HS256"],
        audience="authenticated",
        options={"require": ["exp", "sub"]},
    )


async def get_db(authorization: str | None = None) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session whose request.jwt.claims carry the VERIFIED caller's claims.

    SECURITY: the claims string is built ONLY from the cryptographically verified
    payload — never from any client-supplied blob (a client who could set
    request.jwt.claims directly would own every tenant's rows). Requests without
    a valid Bearer token get NO session at all.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionError("Missing or malformed Authorization header — RLS requires a verified JWT")
    claims = decode_supabase_jwt(authorization.removeprefix("Bearer "))
    sub = claims["sub"]
    async with SessionFactory() as session:
        await session.execute(
            text("SELECT set_config('request.jwt.claims', :claims, true)"),
            {"claims": f'{{"sub": "{sub}", "role": "authenticated"}}'},
        )
        yield session