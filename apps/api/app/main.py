"""FastAPI app — LexSim AI monolith.

Lifespan: Ollama warm-up (pitfall §1) + fail-fast /health/llm per security S4.1 —
`/api/tags` returning 200 is NOT sufficient proof of readiness; a generation must
have completed this boot (or the model must be currently resident per /api/ps).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.llm import get_provider


@asynccontextmanager
async def lifespan(app: FastAPI):
    provider = get_provider()
    app.state.llm = provider
    warmed = False
    try:
        await provider.warmup()  # pins the model (keep_alive=-1) for ollama
        warmed = await provider.health()
    except Exception:  # daemon down or model unpulled — health endpoint reports it
        warmed = False
    app.state.llm_warm = warmed
    yield


app = FastAPI(title="LexSim AI API", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/llm")
async def health_llm() -> dict:
    """S4.1: readiness means warm, not just a 200 from the daemon's tag list."""
    warm = getattr(app.state, "llm_warm", False)
    provider = getattr(app.state, "llm", None)
    return {
        "provider": get_settings().llm_provider,
        "model": getattr(provider, "model", None),
        "warm": warm,
        "ready": warm,
    }


# Routers land here in subsequent PRs:
# from app.cases import router as cases_router
# from app.simulations import router as simulations_router  # SSE live debate viewer
