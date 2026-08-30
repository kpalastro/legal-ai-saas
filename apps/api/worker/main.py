"""arq worker — background jobs (TECH_STACK.md v2.1: arq, NOT Celery).

Jobs:
- run_simulation: executes the 9-turn debate state machine against Bedrock Converse
  (ap-southeast-2 only, model pinned per SECURITY_CHECKLIST S1), streaming turns to
  SSE subscribers via Redis pub/sub, writing audit_log rows per AI call (C1/G5).
- retention_sweep: C3 — cron daily; archive + erase cases older than 7 years unless
  cases.legal_hold is true; cascade covers Storage objects per policy.
"""

from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from app.agents.debate_state_machine import DebateState
from app.config import get_settings

settings = get_settings()


async def run_simulation(ctx: dict, simulation_id: str) -> dict:
    """Run the debate. Idempotent (G-adjacent): re-run resumes from transcript length."""
    state = DebateState(cursor=1)  # TODO: rehydrate cursor from simulations.debate_transcript
    while not state.finished:
        state.advance(content=f"[turn {state.cursor} placeholder — Bedrock wiring lands next PR]")
    return {"simulation_id": simulation_id, "turns": len(state.transcript)}


async def retention_sweep(ctx: dict) -> dict:
    """C3: erase cases past 7y (or per-policy) unless legal_hold. Stubbed until DB wiring."""
    # TODO(C3): SELECT id FROM cases WHERE created_at < NOW() - INTERVAL '7 years'
    #           AND legal_hold = FALSE -> hard delete cascade + storage objects.
    return {"erased": 0, "note": "stub — wire to SQLAlchemy in next PR"}


class WorkerSettings:
    functions = [run_simulation]
    cron_jobs = [cron(retention_sweep, hour=2, minute=0)]  # daily 02:00
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_tries = 3  # arq retry cap (idempotency guard, TEST_PLAN P1)
