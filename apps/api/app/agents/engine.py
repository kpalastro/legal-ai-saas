"""Debate engine — drives DebateState through the LLM provider, one real turn at a time.

Shared by the arq worker (run_simulation) and the SSE router.

Per turn:
  1. Re-arm the transaction: least-privilege role + caller claims (role/claims are
     transaction-local, so a per-turn commit resets them).
  2. Build a case-grounded prompt: intake facts, parties, issues, relief, extracted
     upload text, the transcript so far, and any user interventions.
  3. provider.complete() — OllamaProvider today, BedrockProvider via env in Phase 2.
  4. write_audit_row() — C1/G5: one audit_log + audit_content pair per turn, with
     real prompt/response hashes.
  5. Commit the turn. Audit durability is the point: a client disconnect or a later
     LLM failure must not roll back rows for turns already produced.
  6. state.advance() — the 9-turn protocol cursor (G6).

The caller's session MUST be an AsyncSession (it has commit()). RLS + the audit
INSERT policies do the enforcing; this module never bypasses them.

Nondeterminism contract (TEST_PLAN): tests never assert on prose — only structure
(turn order, audit rows, verdict schema).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable

from sqlalchemy import text

from app.agents.debate_state_machine import DebateState, Turn
from app.agents.prompts import SYSTEM_PROMPTS, verdict_from_text
from app.audit import write_audit_row
from app.db import arm_request
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


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


async def case_context(db, case_id: str) -> str:
    """Case brief from the (RLS-filtered) cases table + extracted upload text.

    The original version selected only title/jurisdiction/cause_of_action, so the
    nine turns argued about a case title. This is the grounding fix.
    """
    row = (
        await db.execute(
            text(
                "SELECT title, jurisdiction, cause_of_action, description, parties,"
                " issues, relief_sought, court, case_number"
                " FROM public.cases WHERE id = :c"
            ),
            {"c": case_id},
        )
    ).mappings().first()
    if row is None:
        raise LookupError(f"case {case_id} not found (or not visible under RLS)")

    parts = [
        f"Case: {row['title']}.",
        f"Court/jurisdiction: {row['court'] or row['jurisdiction']}.",
        f"Cause of action: {row['cause_of_action']}.",
    ]
    if row["case_number"]:
        parts.append(f"Court file number: {row['case_number']}.")
    if row["description"]:
        parts.append(f"Facts as stated by the party:\n{row['description']}")
    if row["parties"]:
        parts.append(f"Parties: {_json(row['parties'])}")
    if row["issues"]:
        issues = row["issues"]
        rendered = "; ".join(str(i) for i in issues) if isinstance(issues, list) else str(issues)
        parts.append(f"Issues to determine: {rendered}")
    if row["relief_sought"]:
        parts.append(f"Relief sought: {row['relief_sought']}")

    docs = (
        await db.execute(
            text(
                "SELECT original_filename, extracted_text FROM public.documents"
                " WHERE case_id = :c AND extracted_text IS NOT NULL"
                " ORDER BY uploaded_at DESC LIMIT 5"
            ),
            {"c": case_id},
        )
    ).mappings().all()
    if docs:
        chunks: list[str] = []
        budget = 8000
        for doc in docs:
            extracted = (doc["extracted_text"] or "").strip()
            if not extracted or budget <= 0:
                continue
            take = extracted[:budget]
            chunks.append(f"--- {doc['original_filename'] or 'document'} ---\n{take}")
            budget -= len(take)
        if chunks:
            parts.append("Uploaded materials (extracted text):\n" + "\n\n".join(chunks))

    return "\n\n".join(parts)


def _format_history(transcript: list[dict], max_chars: int = 12_000) -> str:
    if not transcript:
        return ""
    rendered = "\n\n".join(
        f"Turn {t['turn']} ({t['role']} — {t['name']}): {t['content']}" for t in transcript
    )
    return rendered[-max_chars:]


async def run_debate(
    db,
    *,
    case_id: str,
    user_id: str,
    provider,
    on_turn: "TurnHook | None" = None,
    interventions: list[str] | None = None,
) -> list[dict]:
    """Run all 9 turns against the provider, auditing and committing each turn.

    Returns the transcript — a list of 9 payload dicts in protocol order; the last
    carries `verdict` ({lower, point, upper, note: "not legal advice"} or the
    unparseable-raw fallback, which still renders as a range guard downstream).
    """
    context = await case_context(db, case_id)
    state = DebateState(interventions=list(interventions or []))
    transcript: list[dict] = []

    while not state.finished:
        await arm_request(db, user_id=user_id)  # role/claims are transaction-local
        turn = state.current_turn()
        system = SYSTEM_PROMPTS[turn.role.value]

        history = _format_history(transcript)
        intervention_note = ""
        if state.interventions:
            intervention_note = "\n\nUser instructions for this simulation:\n" + "\n".join(
                f"- {note}" for note in state.interventions
            )
        user_content = (
            f"{context}{intervention_note}\n\n"
            f"{'Transcript so far:' + chr(10) + history if history else 'This is the first turn.'}"
            f"\n\nTurn {turn.index}/9 — {turn_prompt(turn)}"
        )

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

        prompt_text = f"{system}\n\n{user_content}"
        await write_audit_row(
            db,
            case_id=case_id,
            user_id=user_id,
            event_type=f"debate_turn_{executed.index}",
            model_id=resp.model,
            prompt_text=prompt_text,  # verbatim input — LPP trail
            response_text=resp.text,  # verbatim output
            prompt_sha=_sha(prompt_text),
            response_sha=_sha(resp.text),
        )
        # C1/G5 durability: one committed audit pair per turn. If the client
        # disconnects or turn N fails, turns 1..N-1 remain reconstructable.
        commit = getattr(db, "commit", None)
        if commit is not None:
            await commit()

        if on_turn is not None:
            await on_turn(payload)

    return transcript
