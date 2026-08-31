"""arq worker (TECH_STACK.md v2.1) — REAL debate execution + C3 retention sweep.

run_simulation: drives the 9-turn protocol through get_provider() (Ollama today,
Bedrock via env swap in Phase 2) as the case owner's verified identity, writing one
audit_log/audit_content pair per turn (C1/G5) and persisting the transcript +
calibrated verdict on completion (test_worker_audit_contract.py is the net).

retention_sweep: C3 — nightly archive of cases past the 7-year window unless
legal_hold (idempotent: each case matches once; a re-run archives 0).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.engine import run_debate
from app.config import get_settings
from app.llm import get_provider

RETENTION_YEARS = 7  # C3 control (APP; legal-hold override honoured)


async def run_simulation(ctx: dict, case_id: str, user_id: str) -> dict:
    """Execute the debate as the case owner.

    Security shape (security audit, test_worker_audit_contract):
    - claims GUC is set once per transaction, from the *user_id argument the API
      resolved from a verified JWT* — the worker never accepts a raw claims blob.
    - every turn writes audit_log + audit_content through write_audit_row() under
      those claims (C1/G5), enforced by RLS as the app role in prod wiring.
    """
    engine = create_async_engine(get_settings().database_url)
    provider = get_provider()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('request.jwt.claims', :claims, true)"),
                {"claims": json.dumps({"sub": user_id, "role": "authenticated"})},
            )
            transcript = await run_debate(
                conn, case_id=case_id, user_id=user_id, provider=provider
            )
            await persist_result(conn, case_id=case_id, transcript=transcript)
    finally:
        await engine.dispose()
    return {
        "case_id": case_id,
        "turns": len(transcript),
        "verdict": transcript[-1].get("verdict") if transcript else None,
    }


async def persist_result(conn, *, case_id: str, transcript: list[dict]) -> None:
    """Persist transcript + calibrated verdict on a simulations row for the case."""
    await conn.execute(
        text(
            "INSERT INTO simulations (case_id, debate_transcript, outcome_prediction)"
            " VALUES (:c, CAST(:t AS jsonb), CAST(:o AS jsonb))"
        ),
        {
            "c": case_id,
            "t": json.dumps(transcript),
            "o": json.dumps(transcript[-1].get("verdict", {}) if transcript else {}),
        },
    )


async def retention_sweep(ctx: dict) -> dict:
    """C3 — idempotent archive sweep (hard erasure + Storage purge = next PR)."""
    engine = create_async_engine(get_settings().database_url)
    cutoff = (datetime.now(UTC) - timedelta(days=365 * RETENTION_YEARS)).date()
    try:
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "UPDATE cases SET status='archived', updated_at=NOW()"
                        " WHERE created_at < :cutoff AND legal_hold = FALSE"
                        " AND status <> 'archived' RETURNING id"
                    ),
                    {"cutoff": cutoff},
                )
            ).fetchall()
            return {"archived": len(rows), "erased": 0, "cutoff": cutoff.isoformat()}
    finally:
        await engine.dispose()


class WorkerSettings:
    functions = [run_simulation, retention_sweep]
    cron_jobs = [cron(retention_sweep, hour=2, minute=0)]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3  # retry cap (idempotency guard, TEST_PLAN P1)