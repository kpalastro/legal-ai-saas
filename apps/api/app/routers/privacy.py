"""Privacy endpoints: data export, de-identification, legal hold.

APP 12 (access) and APP 13 (correction/erasure) are implemented as:
  * a portable JSON export of the caller's matter data;
  * a de-identification erasure that preserves the append-only audit trail;
  * a legal-hold flag that blocks erasure/retention while litigation is on foot.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import write_audit_row
from app.db import get_db
from app.identity import delete_identity
from app.organisations import require_case_writer
from app.privacy import delete_uploads, erase_user
from app.ratelimit import rate_limit

router = APIRouter(tags=["privacy"])


async def _caller_sub(db: AsyncSession) -> str:
    sub = (
        await db.execute(
            text("SELECT current_setting('request.jwt.claims', true)::jsonb ->> 'sub'")
        )
    ).scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=401, detail="no verified identity on the session")
    return str(sub)


@router.get("/users/me/export", dependencies=[Depends(rate_limit("export", 5, 60))])
async def export_my_data(db: AsyncSession = Depends(get_db)) -> dict:
    sub = await _caller_sub(db)

    async def rows(query: str, params: dict | None = None) -> list[dict]:
        result = await db.execute(text(query), params or {})
        return [dict(row) for row in result.mappings().all()]

    user_rows = await rows(
        "SELECT id, email, role, subscription_tier, created_at, erased_at"
        " FROM public.users WHERE id = :u",
        {"u": sub},
    )
    cases = await rows(
        "SELECT * FROM public.cases WHERE user_id = :u ORDER BY created_at", {"u": sub}
    )
    simulations = await rows(
        "SELECT s.* FROM public.simulations s JOIN public.cases c ON c.id = s.case_id"
        " WHERE c.user_id = :u ORDER BY s.created_at",
        {"u": sub},
    )
    documents = await rows(
        "SELECT d.* FROM public.documents d JOIN public.cases c ON c.id = d.case_id"
        " WHERE c.user_id = :u ORDER BY d.uploaded_at",
        {"u": sub},
    )
    generated = await rows(
        "SELECT g.* FROM public.generated_documents g JOIN public.cases c ON c.id = g.case_id"
        " WHERE c.user_id = :u ORDER BY g.created_at",
        {"u": sub},
    )
    deadlines = await rows(
        "SELECT d.* FROM public.deadlines d JOIN public.cases c ON c.id = d.case_id"
        " WHERE c.user_id = :u ORDER BY d.due_date",
        {"u": sub},
    )
    audit: list[dict] = []
    for case in cases:
        audit.extend(
            await rows(
                "SELECT id, case_id, event_type, model_id, prompt_version, model_digest,"
                " created_at FROM public.audit_log"
                " WHERE case_id = :c ORDER BY created_at",
                {"c": case["id"]},
            )
        )

    return {
        "format_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "user": user_rows[0] if user_rows else None,
        "cases": cases,
        "simulations": simulations,
        "documents": documents,
        "generated_documents": generated,
        "deadlines": deadlines,
        "audit_metadata": audit,
        "note": (
            "This export contains your matter data. Audit records are retained to "
            "evidence AI assistance and may be subject to legal-hold obligations; "
            "their verbatim prompt/response content is not tenant-readable."
        ),
    }


class EraseBody(BaseModel):
    confirm: str


@router.post("/users/me/erase", dependencies=[Depends(rate_limit("erase", 3, 3600))])
async def erase_my_account(body: EraseBody, db: AsyncSession = Depends(get_db)) -> dict:
    if body.confirm != "ERASE":
        raise HTTPException(status_code=422, detail='send {"confirm": "ERASE"} to proceed')
    sub = await _caller_sub(db)
    try:
        paths, case_count = await erase_user(db, sub)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None

    await write_audit_row(
        db,
        case_id=None,
        user_id=sub,
        event_type="account_erased",
        model_id="system",
        prompt_text="account erasure request",
        response_text=f"de-identified {case_count} case(s); audit trail retained",
    )
    await db.commit()
    removed = delete_uploads(paths)
    identity_deleted = await delete_identity(sub)
    return {
        "erased": True,
        "cases_deidentified": case_count,
        "uploads_removed": removed,
        "audit_retained": True,
        "identity_deleted": identity_deleted,
        "note": (
            "Case content and raw uploads were removed/de-identified. Append-only "
            "audit records are retained for LPP/legal obligations. "
            + (
                "The GoTrue identity was deleted."
                if identity_deleted
                else "The GoTrue identity was not deleted — configure the admin API "
                "or delete it in the auth console."
            )
        ),
    }


class LegalHoldBody(BaseModel):
    legal_hold: bool


@router.post("/cases/{case_id}/legal-hold")
async def set_legal_hold(
    case_id: str, body: LegalHoldBody, db: AsyncSession = Depends(get_db)
) -> dict:
    await require_case_writer(db, case_id)
    row = (
        await db.execute(
            text(
                "UPDATE public.cases SET legal_hold = :b WHERE id = :id"
                " RETURNING id, legal_hold"
            ),
            {"b": body.legal_hold, "id": case_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="case not found")
    sub = await _caller_sub(db)
    await write_audit_row(
        db,
        case_id=str(row["id"]),
        user_id=sub,
        event_type="legal_hold_set",
        model_id="system",
        prompt_text=f"legal_hold={body.legal_hold}",
        response_text="legal hold updated",
    )
    await db.commit()
    return {"id": str(row["id"]), "legal_hold": row["legal_hold"]}
