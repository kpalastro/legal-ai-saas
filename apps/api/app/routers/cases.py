"""Case API + SSE live debate stream.

Auth: every endpoint requires a verified Bearer JWT (app.db.get_db is fail-closed).
RLS scopes reads; user_id for writes comes from the verified claims GUC.

The simulation path is transactionally honest: the case is claimed as
`simulating` before the stream starts, each turn is audited + committed by the
engine, and a disconnect/failure resets the case to `intake` without losing the
audit rows for turns already completed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.debate_state_machine import AgentRole
from app.agents.engine import case_context, run_debate
from app.agents.prompts import (
    ANALYSIS_INSTRUCTION,
    ANALYSIS_SYSTEM,
    PROMPT_VERSION,
    parse_weakness_report,
)
from app.audit import write_audit_row
from app.citations import verify_citations
from app.db import SessionFactory, arm_request, get_db
from app.entitlements import enforce_case_limit, enforce_simulation_limit
from app.organisations import require_case_writer
from app.llm.base import LLMRequest
from app.llm.presets import options_for
from app.ratelimit import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cases", tags=["cases"])
simulations_router = APIRouter(prefix="/simulations", tags=["simulations"])


class CaseCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    jurisdiction: str = Field(min_length=2, max_length=120)
    cause_of_action: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    parties: list[dict] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    relief_sought: str | None = Field(default=None, max_length=5_000)
    court: str | None = Field(default=None, max_length=200)
    case_number: str | None = Field(default=None, max_length=100)
    org_id: str | None = None


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    jurisdiction: str | None = Field(default=None, min_length=2, max_length=120)
    cause_of_action: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    parties: list[dict] | None = None
    issues: list[str] | None = None
    relief_sought: str | None = Field(default=None, max_length=5_000)
    court: str | None = Field(default=None, max_length=200)
    case_number: str | None = Field(default=None, max_length=100)


async def _caller_sub(db: AsyncSession) -> str:
    """Caller's sub, from the claims GUC app.db.get_db set from the VERIFIED JWT."""
    result = await db.execute(
        text("SELECT current_setting('request.jwt.claims', true)::jsonb ->> 'sub'")
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=401, detail="no verified identity on the session")
    return str(sub)


async def _mirror_user(db: AsyncSession, sub: str, email: str | None) -> None:
    """Mirror the GoTrue user into the app DB.

    Dev uses an `auth.users` stub the app role may write; hosted Supabase owns
    that table (the row already exists, and the app role usually cannot INSERT
    into it). The savepoint keeps that portability difference from aborting the
    whole request — the public.users FK still needs the row to be present.
    """
    try:
        async with db.begin_nested():
            await db.execute(
                text("INSERT INTO auth.users (id) VALUES (:u) ON CONFLICT (id) DO NOTHING"),
                {"u": sub},
            )
    except Exception:  # noqa: BLE001 — hosted Supabase: auth.users is read-only to us
        logger.debug("auth.users mirror skipped (hosted Supabase owns the table)")
    await db.execute(
        text(
            "INSERT INTO public.users (id, email, role) VALUES (:u, :e, 'individual')"
            " ON CONFLICT (id) DO NOTHING"
        ),
        {"u": sub, "e": email or f"{sub}@unknown.local"},
    )


def _case_dict(row) -> dict:
    data = dict(row)
    for key in ("created_at", "updated_at"):
        if data.get(key) is not None:
            data[key] = data[key].isoformat()
    for key in ("parties", "issues"):
        if data.get(key) is None:
            data[key] = []
    return data


@router.post("", status_code=201)
async def create_case(body: CaseCreate, db: AsyncSession = Depends(get_db)) -> dict:
    sub = await _caller_sub(db)
    await _mirror_user(db, sub, db.info.get("user_email"))
    await enforce_case_limit(db, sub)
    if body.org_id:
        writer = (
            await db.execute(
                text("SELECT public.is_org_writer(:o) AS ok"), {"o": body.org_id}
            )
        ).scalar_one_or_none()
        if writer is not True:
            raise HTTPException(
                status_code=403,
                detail="you need a writer role in the target organisation",
            )
    result = await db.execute(
        text(
            "INSERT INTO public.cases"
            " (user_id, org_id, title, jurisdiction, cause_of_action, description,"
            "  parties, issues, relief_sought, court, case_number)"
            " VALUES (:u, :org, :t, :j, :a, :d, CAST(:p AS jsonb), CAST(:i AS jsonb),"
            "         :r, :court, :num)"
            " RETURNING id, status"
        ),
        {
            "u": sub,
            "org": body.org_id,
            "t": body.title,
            "j": body.jurisdiction,
            "a": body.cause_of_action,
            "d": body.description,
            "p": json.dumps(body.parties),
            "i": json.dumps(body.issues),
            "r": body.relief_sought,
            "court": body.court,
            "num": body.case_number,
        },
    )
    row = result.one()
    await db.commit()
    return {"id": str(row.id), "status": str(row.status)}


@router.get("")
async def list_cases(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT id, org_id, title, jurisdiction, court, cause_of_action, status,"
                " created_at, updated_at"
                " FROM public.cases ORDER BY created_at DESC LIMIT :l OFFSET :o"
            ),
            {"l": limit, "o": offset},
        )
    ).mappings().all()
    return [
        {
            **{k: r[k] for k in ("title", "jurisdiction", "court", "cause_of_action", "status")},
            "id": str(r["id"]),
            "org_id": str(r["org_id"]) if r["org_id"] else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
        }
        for r in rows
    ]


@router.get("/{case_id}")
async def get_case(case_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = (
        await db.execute(
            text(
                "SELECT c.*,"
                " (SELECT count(*) FROM public.simulations s WHERE s.case_id = c.id) AS simulation_count,"
                " (SELECT count(*) FROM public.documents d WHERE d.case_id = c.id) AS document_count,"
                " (SELECT count(*) FROM public.generated_documents g WHERE g.case_id = c.id) AS generated_document_count,"
                " (SELECT count(*) FROM public.deadlines dl WHERE dl.case_id = c.id) AS deadline_count"
                " FROM public.cases c WHERE c.id = :id"
            ),
            {"id": case_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="case not found")
    return _case_dict(row)


@router.patch("/{case_id}")
async def update_case(
    case_id: str, body: CaseUpdate, db: AsyncSession = Depends(get_db)
) -> dict:
    provided = body.model_dump(exclude_unset=True)
    if not provided:
        raise HTTPException(status_code=422, detail="no fields to update")

    clauses: list[str] = []
    params: dict = {"id": case_id}
    for key, value in provided.items():
        if key in ("parties", "issues"):
            clauses.append(f"{key} = CAST(:{key} AS jsonb)")
            params[key] = json.dumps(value)
        else:
            clauses.append(f"{key} = :{key}")
            params[key] = value
    row = (
        await db.execute(
            text(
                f"UPDATE public.cases SET {', '.join(clauses)}"
                " WHERE id = :id RETURNING id, status, updated_at"
            ),
            params,
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="case not found")
    await db.commit()
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.get("/{case_id}/simulations")
async def list_simulations(case_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT id, status, outcome_prediction, user_attestation,"
                " user_attested_at, created_at"
                " FROM public.simulations WHERE case_id = :c ORDER BY created_at DESC"
            ),
            {"c": case_id},
        )
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "status": r["status"],
            "outcome_prediction": r["outcome_prediction"],
            "user_attestation": r["user_attestation"],
            "user_attested_at": r["user_attested_at"].isoformat()
            if r["user_attested_at"]
            else None,
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@simulations_router.get("/{simulation_id}")
async def get_simulation(simulation_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = (
        await db.execute(
            text(
                "SELECT id, case_id, status, debate_transcript, outcome_prediction,"
                " weakness_report, hallucination_score, user_attestation,"
                " user_attested_at, created_at"
                " FROM public.simulations WHERE id = :id"
            ),
            {"id": simulation_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="simulation not found")
    return {
        **dict(row),
        "id": str(row["id"]),
        "case_id": str(row["case_id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "user_attested_at": row["user_attested_at"].isoformat()
        if row["user_attested_at"]
        else None,
    }


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _citation_risk(findings) -> tuple[float, str]:
    """Map verified / unverified / flagged citations to a 0-1 risk score."""
    if not findings:
        return 0.0, "no citations detected in the transcript"
    weights = {
        "verified": 0.0,
        "unverified": 0.5,
        "flagged": 1.0,
    }
    score = sum(weights.get(f.status.value, 0.5) for f in findings) / len(findings)
    return round(score, 3), f"{len(findings)} citation(s) checked"


class AnalysisBody(BaseModel):
    verify_citations: bool = True


@simulations_router.post(
    "/{simulation_id}/analysis",
    dependencies=[Depends(rate_limit("analysis", 10, 60))],
)
async def analyse_simulation(
    simulation_id: str,
    body: AnalysisBody | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Post-debate weakness analysis. Not a tenth protocol turn (G6 is fixed)."""
    from app.llm import get_provider

    row = (
        await db.execute(
            text(
                "SELECT id, case_id, status, debate_transcript"
                " FROM public.simulations WHERE id = :id"
            ),
            {"id": simulation_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="simulation not found")
    if row["status"] != "completed":
        raise HTTPException(status_code=409, detail="simulation is not completed")

    case_id = str(row["case_id"])
    await require_case_writer(db, case_id)
    context = await case_context(db, case_id)
    turns = row["debate_transcript"] or []
    transcript = "\n\n".join(
        f"Turn {turn.get('turn')} ({turn.get('role')} — {turn.get('name')}): "
        f"{turn.get('content')}"
        for turn in turns
        if isinstance(turn, dict)
    )[:20_000]

    user_prompt = f"{context}\n\nTRANSCRIPT:\n{transcript}\n\n{ANALYSIS_INSTRUCTION}"
    provider = get_provider()
    try:
        response = await provider.complete(
            LLMRequest(
                system=ANALYSIS_SYSTEM,
                user=user_prompt,
                options=options_for(AgentRole.JUDGE),
                max_tokens=1_500,
            )
        )
    except Exception:  # noqa: BLE001 — provider failure is a 502, not a 500
        logger.exception("analysis provider failed for simulation %s", simulation_id)
        raise HTTPException(status_code=502, detail="analysis provider failed") from None

    report = parse_weakness_report(response.text)
    findings = (
        await verify_citations(transcript)
        if (body is None or body.verify_citations)
        else []
    )
    score, risk_note = _citation_risk(findings)
    report["citation_risk"] = {
        "score": score,
        "note": risk_note,
        "checked": len(findings),
    }

    await db.execute(
        text(
            "UPDATE public.simulations"
            " SET weakness_report = CAST(:w AS jsonb), hallucination_score = :s"
            " WHERE id = :id"
        ),
        {"w": json.dumps(report), "s": score, "id": simulation_id},
    )
    await write_audit_row(
        db,
        case_id=case_id,
        user_id=await _caller_sub(db),
        event_type="simulation_analysis",
        model_id=response.model,
        prompt_text=f"{ANALYSIS_SYSTEM}\n\n{user_prompt}",
        response_text=response.text,
        prompt_sha=_sha(f"{ANALYSIS_SYSTEM}\n\n{user_prompt}"),
        response_sha=_sha(response.text),
        prompt_version=PROMPT_VERSION,
        model_digest=getattr(response, "digest", None),
    )
    await db.commit()
    return {
        "simulation_id": simulation_id,
        "weakness_report": report,
        "hallucination_score": score,
        "citation_risk": report["citation_risk"],
    }


class AttestSimulationBody(BaseModel):
    user_attestation: bool


@simulations_router.post("/{simulation_id}/attest")
async def attest_simulation(
    simulation_id: str,
    body: AttestSimulationBody,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not body.user_attestation:
        raise HTTPException(status_code=422, detail="user_attestation must be true to attest")
    case_row = (
        await db.execute(
            text("SELECT case_id FROM public.simulations WHERE id = :id"),
            {"id": simulation_id},
        )
    ).scalar_one_or_none()
    if case_row is None:
        raise HTTPException(status_code=404, detail="simulation not found")
    await require_case_writer(db, str(case_row))
    row = (
        await db.execute(
            text(
                "UPDATE public.simulations"
                " SET user_attestation = true, user_attested_at = NOW()"
                " WHERE id = :id RETURNING id, user_attested_at"
            ),
            {"id": simulation_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="simulation not found")
    await db.commit()
    return {
        "id": str(row["id"]),
        "user_attestation": True,
        "user_attested_at": row["user_attested_at"].isoformat(),
    }


async def _reset_case_status(case_id: str, user_id: str) -> None:
    """Best-effort reset after a failed/cancelled stream, on a fresh session."""
    try:
        async with SessionFactory() as session:
            await arm_request(session, user_id=user_id)
            await session.execute(
                text("UPDATE public.cases SET status='intake' WHERE id=:c AND status='simulating'"),
                {"c": case_id},
            )
            await session.commit()
    except Exception:  # never mask the original failure
        logger.exception("failed to reset case %s after stream failure", case_id)


@router.get("/{case_id}/simulate")
async def simulate_sse(
    case_id: str,
    interventions: list[str] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    sub = await _caller_sub(db)
    await require_case_writer(db, case_id)
    await enforce_simulation_limit(db, sub)
    from app.llm import get_provider

    notes = [n.strip()[:2_000] for n in (interventions or []) if n and n.strip()][:10]

    # Serialise runs per case: claim the case before streaming. A second client
    # gets a clean 409 instead of two debates writing interleaved audit rows.
    exists = (
        await db.execute(text("SELECT 1 FROM public.cases WHERE id = :c"), {"c": case_id})
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="case not found")
    claimed = (
        await db.execute(
            text(
                "UPDATE public.cases SET status='simulating'"
                " WHERE id = :c"
                "   AND (status <> 'simulating'"
                # Recover from a crashed run: 9 turns is well under an hour, so a
                # `simulating` row older than this is stale, not active.
                "        OR updated_at < NOW() - INTERVAL '60 minutes')"
                " RETURNING id"
            ),
            {"c": case_id},
        )
    ).scalar_one_or_none()
    if claimed is None:
        raise HTTPException(status_code=409, detail="a simulation is already running for this case")
    await db.commit()

    provider = get_provider()

    async def event_source() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()

        async def hook(payload: dict) -> None:
            await queue.put({"event": "turn", "payload": payload})

        async def runner() -> None:
            try:
                transcript = await run_debate(
                    db,
                    case_id=case_id,
                    user_id=sub,
                    provider=provider,
                    on_turn=hook,
                    interventions=notes,
                )
                # C5/G2 chain: documents link to this simulation and the export
                # gate reads simulations.user_attestation.
                from worker.main import persist_result

                simulation_id = await persist_result(
                    db, case_id=case_id, transcript=transcript
                )
                await db.commit()
                await queue.put(
                    {
                        "event": "done",
                        "payload": {
                            "simulation_id": simulation_id,
                            "verdict": transcript[-1].get("verdict") if transcript else None,
                        },
                    }
                )
            except asyncio.CancelledError:
                await _reset_case_status(case_id, sub)
                raise
            except Exception:  # noqa: BLE001 — surfaced as a generic SSE error
                logger.exception("simulation failed for case %s", case_id)
                await _reset_case_status(case_id, sub)
                await queue.put(
                    {"event": "error", "payload": {"detail": "simulation failed"}}
                )

        task = asyncio.create_task(runner())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": ping\n\n"  # keep proxies from idling out a long turn
                    continue
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
