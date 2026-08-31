"""Routers for feature 4 (documents + citations), 5 (deadlines), 6 (billing).

Schema-aligned with the live DB: generated_documents carries `citations` jsonb +
`user_reviewed` + `exported` + `export_blocked_reason`; user_attestation lives on
the parent simulation (C5). The DB triggers enforce_export_citations/_attestation
are the primary gate — the API's 403 export check here is the same contract
expressed at the HTTP layer so a client sees a clean error, not a trigger crash.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.citations import verify_citations
from app.db import get_db
from app.deadlines import compute_deadline
from app.deadlines.service import disclaimer
from app.documents.generator import render_document, DISCLOSURE_FOOTER
from app.documents.registry import require_allowed_doc_type

router = APIRouter()


# ---------- Feature 4: documents + citations ----------

class DocGenerateBody(BaseModel):
    case_id: str
    doc_type: str
    jurisdiction: str
    fields: dict
    verify: bool = True  # run citation verification over `fields` text values


@router.post("/documents/generate")
async def generate_document(body: DocGenerateBody, db: AsyncSession = Depends(get_db)) -> dict:
    doc_type = require_allowed_doc_type(body.doc_type)  # G3: 422 on prohibited
    cite_rows: list[dict] = []
    if body.verify:
        text_blob = "\n".join(str(v) for v in body.fields.values() if isinstance(v, (str, list, dict)))
        findings = await verify_citations(text_blob)
        cite_rows = [
            {"raw": f.raw, "status": f.status.value, "source": f.source, "url": f.url}
            for f in findings
        ]
    content = render_document(body.doc_type, body.jurisdiction, body.fields, citations=cite_rows)

    # Verify the case exists & is visible under RLS before attaching a doc to it.
    case = (await db.execute(
        text("SELECT id FROM cases WHERE id = :id"), {"id": body.case_id}
    )).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found (or not yours)")

    export_ready = all(c["status"] == "verified" for c in cite_rows) if cite_rows else False
    r = await db.execute(
        text("""INSERT INTO generated_documents (case_id, doc_type, content, citations, user_reviewed, exported, export_blocked_reason)
                VALUES (:c, :t, :ct, CAST(:cv AS jsonb), false, false, :reason)
                RETURNING id"""),
        {
            "c": body.case_id,
            "t": body.doc_type,
            "ct": content,
            "cv": json.dumps(cite_rows),
            "reason": None if export_ready else "citations unverified + user review pending (SC Gen 23 para 17)",
        },
    )
    doc_id = r.scalar_one()
    await db.commit()
    return {
        "id": str(doc_id),
        "doc_type": doc_type.value,
        "content": content,
        "citations": cite_rows,
        "export_ready": export_ready,
        "next_step": "review citations, verify them, then attest at POST /documents/{id}/attest",
    }


class AttestBody(BaseModel):
    user_reviewed: bool = True


@router.post("/documents/{doc_id}/attest")
async def attest_document(doc_id: str, body: AttestBody, db: AsyncSession = Depends(get_db)) -> dict:
    if not body.user_reviewed:
        raise HTTPException(status_code=422, detail="user_reviewed must be true to attest")
    current = (await db.execute(
        text("SELECT citations, exported FROM generated_documents WHERE id=:id"),
        {"id": doc_id},
    )).mappings().first()
    if current is None:
        raise HTTPException(status_code=404, detail="document not found")
    rows = current["citations"] or []
    unverified = [c for c in rows if c.get("status") != "verified"]
    if current["exported"]:
        raise HTTPException(status_code=409, detail="document already exported")
    if unverified:
        # do NOT let attest flip review on a doc whose citations are not
        # verified — the DB trigger would still block, but state stays coherent
        raise HTTPException(
            status_code=409,
            detail=f"{len(unverified)} citation(s) unverified — verify before attesting (SC Gen 23 para 17)",
        )
    r = await db.execute(
        text("UPDATE generated_documents SET user_reviewed=true WHERE id=:id RETURNING id"),
        {"id": doc_id},
    )
    await db.commit()
    return {"id": doc_id, "user_reviewed": True, "citations_all_verified": True}


@router.get("/documents/{doc_id}/export")
async def export_document(doc_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = (await db.execute(
        text("""SELECT id, doc_type, content, citations, user_reviewed, exported, export_blocked_reason
                FROM generated_documents WHERE id = :id"""),
        {"id": doc_id},
    )).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    rows = row["citations"] or []
    unverified = [c for c in rows if c.get("status") != "verified"]
    if unverified:
        raise HTTPException(status_code=403, detail=f"export blocked: {len(unverified)} citation(s) not verified (SC Gen 23 para 17)")
    if not row["user_reviewed"]:
        raise HTTPException(status_code=403, detail="export blocked: user has not reviewed the document")
    att = (await db.execute(
        text("""SELECT s.user_attestation FROM simulations s
                WHERE s.id = (SELECT simulation_id FROM generated_documents WHERE id=:id)"""),
        {"id": doc_id},
    )).scalar_one_or_none()
    if att is None or att is not True:
        raise HTTPException(status_code=403, detail="export blocked: simulation attestation missing (SC Gen 23)")
    r = await db.execute(
        text("UPDATE generated_documents SET exported=true, export_blocked_reason=NULL WHERE id=:id RETURNING id"),
        {"id": doc_id},
    )
    await db.commit()
    return {"id": str(row["id"]), "doc_type": row["doc_type"], "content": row["content"], "exported_at": datetime.now(UTC).isoformat()}


@router.post("/citations/verify")
async def verify(body: dict, db: AsyncSession = Depends(get_db)) -> dict:
    result = await verify_citations(str(body.get("text", "")))
    return {"citations": [{"raw": f.raw, "status": f.status.value, "source": f.source, "url": f.url} for f in result]}


# ---------- Feature 5: deadlines ----------

class DeadlineBody(BaseModel):
    doc_type: str
    jurisdiction: str
    served_on: date | None = None


@router.post("/deadlines/compute")
async def compute(body: DeadlineBody, db: AsyncSession = Depends(get_db)) -> dict:
    result = compute_deadline(body.doc_type, body.jurisdiction, body.served_on)
    if result is None:
        raise HTTPException(status_code=422, detail=f"no deadline rule for {body.doc_type} in {body.jurisdiction}")
    due, respond = result
    return {"due_date": due.isoformat(), "respond_doc": respond, "disclaimer": disclaimer()}


# ---------- Feature 6: billing (Stripe test-mode scaffold) ----------

PRICING = {
    "individual_case_basic": 4900,       # $49
    "individual_case_full": 14900,       # $149
    "lawyer_monthly_10": 9900,           # $99/mo
    "lawyer_monthly_unlimited": 29900,   # $299/mo
}


class CheckoutBody(BaseModel):
    plan: str


@router.post("/billing/checkout")
async def checkout(body: CheckoutBody, db: AsyncSession = Depends(get_db)) -> dict:
    amount = PRICING.get(body.plan)
    if amount is None:
        raise HTTPException(status_code=422, detail=f"unknown plan '{body.plan}'")
    # v1 test-mode scaffold: real stripe SDK lands in Phase 2 prod-hardening.
    return {"mode": "stripe_test", "plan": body.plan, "amount_cents": amount, "currency": "aud", "checkout_url": f"https://checkout.stripe.com/test/{body.plan}"}