"""FastAPI app — LexSim AI monolith.

Routers wired: /cases (create/list) + /cases/{id}/simulate (SSE, live 9-turn
debate through the real provider). Health endpoints unchanged.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError

from app.config import get_settings
from app.llm import get_provider
from app.middleware import RequestContextMiddleware
from app.routers.cases import router as cases_router
from app.routers.cases import simulations_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    provider = get_provider()
    app.state.llm = provider
    warmed = False
    try:
        await provider.warmup()  # pins the model (keep_alive=-1) — pitfall §1
        warmed = await provider.health()
    except Exception:
        warmed = False
    app.state.llm_warm = warmed
    yield


app = FastAPI(title="LexSim AI API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(DataError)
async def data_error_handler(request: Request, exc: DataError) -> JSONResponse:
    """A malformed UUID/path identifier is a client error, not a 500."""
    return JSONResponse(
        {"detail": "invalid identifier or value", "request_id": getattr(request.state, "request_id", None)},
        status_code=422,
    )

# The web app (localhost:3000) calls this API cross-origin from the browser.
# Without CORS the browser blocks every response and fetch() throws bare
# "TypeError: Failed to fetch" (the UI error screenshot of 31 Aug).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Correlation id, body-size cap, security headers, access log.
app.add_middleware(RequestContextMiddleware)

app.include_router(cases_router)
app.include_router(simulations_router)

# Feature 4/5/6 routers: documents + citations verification, deadline calculator,
# billing scaffold (Stripe test-mode). All inherit fail-closed JWT auth via get_db.
from app.routers.features import router as features_router  # noqa: E402

app.include_router(features_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/llm")
async def health_llm() -> dict:
    """S4.1: readiness = warm this boot, not just a 200 from /api/tags."""
    warm = getattr(app.state, "llm_warm", False)
    provider = getattr(app.state, "llm", None)
    return {
        "provider": get_settings().llm_provider,
        "model": getattr(provider, "model", None),
        "warm": warm,
        "ready": warm,
    }


@app.get("/health/db")
async def health_db() -> dict:
    """Expose the effective DB identity — the RLS bypass risk, visible not assumed.

    A superuser or BYPASSRLS role makes every RLS policy inert. This endpoint is
    intentionally blunt so a misconfigured deployment fails a smoke check.
    """
    from sqlalchemy import text

    from app.db import SessionFactory

    role_probe = text(
        """
        SELECT current_user AS role,
               current_setting('search_path') AS search_path,
               (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS is_superuser,
               (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user) AS bypass_rls,
               (SELECT count(*) FROM pg_tables WHERE schemaname = 'public') AS public_tables,
               (SELECT count(*) FROM pg_tables
                 WHERE schemaname = 'public' AND rowsecurity) AS rls_tables
        """
    )
    async with SessionFactory() as session:
        connection = (await session.execute(role_probe)).mappings().first()
        if connection is None:
            raise RuntimeError("database health query returned no row")
        app_role = get_settings().db_app_role
        if app_role:
            # Same role the request path binds; report the role that actually
            # executes tenant queries, not the privileged connection user.
            await session.execute(text(f"SET LOCAL ROLE {app_role}"))
        effective = (await session.execute(role_probe)).mappings().first()
    if effective is None:
        raise RuntimeError("database health query returned no row")

    data = dict(effective)
    data["rls_enforced"] = not (data["is_superuser"] or data["bypass_rls"])
    data["connection_role"] = connection["role"]
    data["connection_privileged"] = bool(
        connection["is_superuser"] or connection["bypass_rls"]
    )
    data["app_role"] = data.pop("role")
    return data