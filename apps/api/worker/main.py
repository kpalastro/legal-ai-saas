"""arq worker (TECH_STACK.md v2.1) — REAL debate execution + C3 retention sweep.

run_simulation: drives the 9-turn protocol through get_provider() (Ollama today,
Bedrock via env swap in Phase 2) as the case owner's verified identity, writing one
audit_log/audit_content pair per turn (C1/G5) and persisting the transcript +
calibrated verdict on completion (test_worker_audit_contract.py is the net).

retention_sweep: C3 — nightly archive of cases past the 7-year window unless
legal_hold (idempotent: each case matches once; a re-run archives 0).
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
from datetime import UTC, datetime, timedelta
from email.mime.text import MIMEText

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.agents.engine import run_debate
from app.config import get_settings
from app.db import SessionFactory, arm_request
from app.llm import get_provider
from app.privacy import delete_uploads, retention_deidentify

logger = logging.getLogger(__name__)

RETENTION_YEARS = 7  # C3 control (APP; legal-hold override honoured)


async def run_simulation(ctx: dict, case_id: str, user_id: str) -> dict:
    """Execute the debate as the case owner.

    Security shape (security audit, test_worker_audit_contract):
    - claims GUC is set once per transaction, from the *user_id argument the API
      resolved from a verified JWT* — the worker never accepts a raw claims blob.
    - every turn writes audit_log + audit_content through write_audit_row() under
      those claims (C1/G5), enforced by RLS as the app role in prod wiring.
    """
    provider = get_provider()
    try:
        async with SessionFactory() as session:
            # Least-privilege role + verified claims; run_debate re-arms after each
            # per-turn commit (transaction-local role/claims would otherwise reset).
            await arm_request(session, user_id=user_id)
            transcript = await run_debate(
                session, case_id=case_id, user_id=user_id, provider=provider
            )
            await persist_result(session, case_id=case_id, transcript=transcript)
            await session.commit()
    except Exception:
        # Leave the case runnable after a failure, and keep the audit rows already
        # committed by run_debate (per-turn durability).
        async with SessionFactory() as session:
            await arm_request(session, user_id=user_id)
            await session.execute(
                text("UPDATE public.cases SET status='intake' WHERE id=:c"), {"c": case_id}
            )
            await session.commit()
        raise
    return {
        "case_id": case_id,
        "turns": len(transcript),
        "verdict": transcript[-1].get("verdict") if transcript else None,
    }


async def persist_result(conn, *, case_id: str, transcript: list[dict]) -> str:
    """Persist the transcript/verdict and return the new simulation id.

    The id matters: documents link to it, and the export gate needs it to find
    the user's attestation. Case status moves to `completed` here.
    """
    row = (
        await conn.execute(
            text(
                "INSERT INTO public.simulations"
                " (case_id, debate_transcript, outcome_prediction, status)"
                " VALUES (:c, CAST(:t AS jsonb), CAST(:o AS jsonb), 'completed')"
                " RETURNING id"
            ),
            {
                "c": case_id,
                "t": json.dumps(transcript),
                "o": json.dumps(transcript[-1].get("verdict", {}) if transcript else {}),
            },
        )
    ).scalar_one()
    await conn.execute(
        text("UPDATE public.cases SET status='completed' WHERE id=:c"), {"c": case_id}
    )
    return str(row)


async def retention_sweep(ctx: dict) -> dict:
    """C3 — de-identify every case past the 7-year window unless under legal hold.

    Audit rows are intentionally retained (append-only, LPP/legal obligations);
    case content, extracted text, chunks and raw uploads are removed.
    """
    engine = create_async_engine(get_settings().database_url)
    cutoff = (datetime.now(UTC) - timedelta(days=365 * RETENTION_YEARS)).date()
    try:
        async with engine.begin() as conn:
            count, paths = await retention_deidentify(conn, cutoff)
        removed = delete_uploads(paths)
        return {
            "archived": count,
            "erased": count,
            "uploads_removed": removed,
            "cutoff": cutoff.isoformat(),
        }
    finally:
        await engine.dispose()


def _send_email(to: str, subject: str, body: str) -> bool:
    settings = get_settings()
    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = to
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.sendmail(settings.smtp_from, [to], message.as_string())
        return True
    except Exception:  # noqa: BLE001 — leave unsent so the next run retries
        logger.exception("deadline reminder email failed for %s", to)
        return False


async def send_deadline_reminders(ctx: dict) -> dict:
    """Daily: email deadlines due in the next 7 days, once (reminder_sent)."""
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT d.id, d.due_date, d.trigger_doc_type, u.email
                        FROM public.deadlines d
                        JOIN public.cases c ON c.id = d.case_id
                        JOIN public.users u ON u.id = c.user_id
                        WHERE d.reminder_sent = FALSE
                          AND u.erased_at IS NULL
                          AND d.due_date BETWEEN CURRENT_DATE
                                             AND CURRENT_DATE + INTERVAL '7 days'
                        ORDER BY d.due_date
                        """
                    )
                )
            ).mappings().all()
            sent = 0
            for row in rows:
                body = (
                    f"LexSim reminder: {row['trigger_doc_type']} deadline is due "
                    f"{row['due_date']}.\n\n"
                    "This is preparation assistance only — verify the date against "
                    "the court's rules before relying on it.\n"
                )
                if await asyncio.to_thread(
                    _send_email, row["email"], f"LexSim deadline due {row['due_date']}", body
                ):
                    await conn.execute(
                        text(
                            "UPDATE public.deadlines"
                            " SET reminder_sent = TRUE, reminder_sent_at = NOW()"
                            " WHERE id = :id"
                        ),
                        {"id": str(row["id"])},
                    )
                    sent += 1
            return {"due": len(rows), "sent": sent}
    finally:
        await engine.dispose()


class WorkerSettings:
    functions = [run_simulation, retention_sweep, send_deadline_reminders]
    cron_jobs = [
        cron(retention_sweep, hour=2, minute=0),
        cron(send_deadline_reminders, hour=8, minute=0),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3  # retry cap (idempotency guard, TEST_PLAN P1)