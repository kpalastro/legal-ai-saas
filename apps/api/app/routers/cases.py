"""Case API + SSE live debate stream.

Auth: every endpoint requires a verified Bearer JWT (app.db.get_db is fail-closed).
RLS scopes reads; user_id for writes comes from the verified claims GUC.
SSE (not WebSocket, per TECH_STACK.md): GET /cases/{id}/simulate streams the
9-turn debate; each turn persists + audits as it happens (C1/G5).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.engine import run_debate
from app.db import get_db

router = APIRouter(prefix="/cases", tags=["cases"])


class CaseCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    jurisdiction: str
    cause_of_action: str


async def _caller_sub(db: AsyncSession) -> str:
    """Caller's sub, from the claims GUC app.db.get_db set from the VERIFIED JWT."""
    result = await db.execute(
        text("SELECT current_setting('request.jwt.claims', true)::jsonb ->> 'sub'")
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=401, detail="no verified identity on the session")
    return str(sub)


@router.post("", status_code=201)
async def create_case(body: CaseCreate, db: AsyncSession = Depends(get_db)) -> dict:
    sub = await _caller_sub(db)
    # auth mirror, BOTH sides: GoTrue owns the authoritative user (its own `gotrue`
    # DB live; hosted Supabase later), so (1) mirror the stub auth.users row that the
    # FK targets, then (2) the public.users app mirror. Values come from the VERIFIED
    # JWT via session.info (set in get_db) — never client input. On hosted Supabase
    # step 1 is a no-op because auth.users is the real one.
    await db.execute(
        text("INSERT INTO auth.users (id) VALUES (:u) ON CONFLICT (id) DO NOTHING"),
        {"u": sub},
    )
    await db.execute(
        text("INSERT INTO users (id, email, role) VALUES (:u, :e, 'individual')"
             " ON CONFLICT (id) DO NOTHING"),
        {"u": sub, "e": db.info.get("user_email") or f"{sub}@unknown.local"},
    )
    result = await db.execute(
        text(
            "INSERT INTO cases (user_id, title, jurisdiction, cause_of_action)"
            " VALUES (:u, :t, :j, :a) RETURNING id, status"
        ),
        {"u": sub, "t": body.title, "j": body.jurisdiction, "a": body.cause_of_action},
    )
    row = result.first()
    await db.commit()
    return {"id": str(row.id), "status": str(row.status)}


@router.get("")
async def list_cases(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT id, title, jurisdiction, cause_of_action, status"
                " FROM cases ORDER BY created_at DESC"
            )
        )
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": str(r.id),
                "title": r.title,
                "jurisdiction": r.jurisdiction,
                "cause_of_action": r.cause_of_action,
                "status": r.status,
            }
        )
    return out


@router.get("/{case_id}/simulate")
async def simulate_sse(case_id: str, db: AsyncSession = Depends(get_db)):
    sub = await _caller_sub(db)
    from app.llm import get_provider

    provider = get_provider()

    async def event_source() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()

        async def hook(payload: dict) -> None:
            await queue.put({"event": "turn", "payload": payload})

        async def runner() -> None:
            try:
                transcript = await run_debate(
                    db, case_id=case_id, user_id=sub, provider=provider, on_turn=hook
                )
                # C5/G2 chain: the export gate reads simulations.user_attestation —
                # without this row the gate has nothing to gate on after an SSE
                # debate (found by @supervisor's probe: sims table stayed empty).
                from worker.main import persist_result

                await persist_result(db, case_id=case_id, transcript=transcript)
                await db.commit()
                await queue.put({"event": "done", "payload": {}})
            except Exception as exc:  # noqa: BLE001 — surfaced as an SSE error event
                await queue.put({"event": "error", "payload": {"detail": str(exc)}})

        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                data = json.dumps(item["payload"])
                yield f"event: {item['event']}\ndata: {data}\n\n"
                if item["event"] in ("done", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )