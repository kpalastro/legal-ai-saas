"""FastAPI app — LexSim AI monolith.

Routers wired: /cases (create/list) + /cases/{id}/simulate (SSE, live 9-turn
debate through the real provider). Health endpoints unchanged.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.llm import get_provider
from app.routers.cases import router as cases_router


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
app.include_router(cases_router)


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