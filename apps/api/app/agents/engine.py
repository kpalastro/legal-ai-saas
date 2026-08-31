"""Debate engine — drives DebateState through the LLM provider, one real turn at a time.

Shared by the arq worker (run_simulation) and the SSE router (app/routers/simulations).
Per turn:
  1. LLMRequest built from app.llm.presets (role sampler pins + JUDGE seed)
  2. provider.complete() — OllamaProvider today, BedrockProvider via env in Phase 2
  3. write_audit_row() — C1/G5: one audit_log + audit_content pair per turn
  4. state.advance() — the 9-turn protocol cursor (G6)

The caller's session/connection MUST already carry the owner's claims GUC
(app.db.get_db / worker wiring): RLS + the audit INSERT policies do the enforcing;
this module never bypasses them.

Nondeterminism contract (TEST_PLAN): tests never assert on prose — only structure
(turn order, audit rows, verdict schema).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import text

from app.agents.debate_state_machine import DebateState, Turn
from app.agents.prompts import SYSTEM_PROMPTS, verdict_from_text
from app.audit import write_audit_row
from app.llm.base import LLMRequest
from app.llm.presets import options_for, seed_for

TurnHook = Callable[[dict], Awaitable[None]]

_TURN_INSTRUCTION: dict[int, str] = {
    1: "Give the plaintiff's opening statement.",
    2: "Give the defendant's opening statement.",
    3: "Deliver your initial belief update as the JSON object described.",
    4: "Rebut the defendant's opening for the plaintiff.",
    5: "Rebut the plaintiff's opening for the defendant.",
    6: "Give your mid-debate belief update as the JSON object described.",
    7: "Give the plaintiff's closing argument.",
    8: "Give the defendant's closing.",
    9: "Deliver your final verdict. Respond with ONLY the JSON object {lower, point, upper}.",
}


def turn_prompt(turn: Turn) -> str:
    return _TURN_INSTRUCTION[turn.index]


async def case_context(db, case_id: str) -> str:
    """Case brief from the (RLS-filtered) cases table."""
    row = (
        await db.execute(
            text("SELECT title, jurisdiction, cause_of_action FROM cases WHERE id = :c"),
            {"c": case_id},
        )
    ).first()
    if row is None:
        raise LookupError(f"case {case_id} not found (or not visible under RLS)")
    return (
        f"Case: {row.title}. Jurisdiction: {row.jurisdiction}. "
        f"Cause of action: {row.cause_of_action}."
    )


async def run_debate(
    db,
    *,
    case_id: str,
    user_id: str,
    provider,
    on_turn: "TurnHook | None" = None,
) -> list[dict]:
    """Run all 9 turns against the provider, auditing each turn (C1/G5).

    Returns the transcript — a list of 9 payload dicts in protocol order; the last
    carries `verdict` ({lower, point, upper, note: "not legal advice"} or the
    unparseable-raw fallback, which still renders as a range guard downstream).
    """
    context = await case_context(db, case_id)
    state = DebateState()
    transcript: list[dict] = []
    while not state.finished:
        turn = state.current_turn()
        system = SYSTEM_PROMPTS[turn.role.value]
        user_content = f"{context}\n\nTurn {turn.index}/9 — {turn_prompt(turn)}"
        resp = await provider.complete(
            LLMRequest(
                system=system,
                user=user_content,
                options=options_for(turn.role),
                max_tokens=2048,
                seed=seed_for(turn.role),  # JUDGE only — runtime pitfall §4
            )
        )
        executed = state.advance(resp.text)  # G6: linear cursor, no out-of-order
        payload = {
            "turn": executed.index,
            "role": executed.role.value,
            "name": executed.name,
            "content": resp.text,
            "is_belief_update": executed.is_belief_update,
        }
        if executed.index == 9:  # calibrated range + not-legal-advice copy (ACL s18/s29)
            payload["verdict"] = verdict_from_text(resp.text)
        transcript.append(payload)
        await write_audit_row(
            db,
            case_id=case_id,
            user_id=user_id,
            event_type=f"debate_turn_{executed.index}",
            model_id=resp.model,
            prompt_text=f"{system}\n\n{user_content}",  # verbatim input — LPP trail
            response_text=resp.text,  # verbatim output
            prompt_sha=None,
            response_sha=None,
        )
        if on_turn is not None:
            await on_turn(payload)
    return transcript