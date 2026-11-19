"""Feature routers: uploads, document generation/attest/export, citations,
deadlines/limitations, and Stripe billing.

Design rules:
  * Every document carries its verification record and the AI-assistance footer.
  * Export is gated at three layers: API checks, DB triggers, RLS visibility.
  * A generated document links to a simulation so the SC Gen 23 attestation gate
    has a row to read; export is impossible without that link + attestation.
  * Uploads are metadata + extracted text; the raw file is never served by the API.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import (
    PLANS,
    BillingUnavailable,
    WebhookError,
    create_checkout_session,
    entitlement_from_event,
    verify_webhook,
)
from app.citations import CitationFinding, verify_citations
from app.config import get_settings
from app.db import SessionFactory, get_db
from app.deadlines import compute_deadline, compute_limitation
from app.deadlines.service import disclaimer
from app.documents.exporters import export_bytes
from app.documents.generator import render_document
from app.documents.registry import require_allowed_doc_type
from app.documents.storage import UploadError, extract_text, save_upload
from app.ratelimit import rate_limit

logger = logging.getLogger(__name__)

router = APIRouter()


def _finding_dict(finding: CitationFinding) -> dict:
    return {
        "raw": finding.raw,
        "status": finding.status.value,
        "source": finding.source,
        "url": finding.url,
        "checked_at": finding.checked_at,
        "evidence": finding.evidence,
    }


async def _case_exists(db: AsyncSession, case_id: str) -> bool:
    row = (
        await db.execute(text("SELECT 1 FROM public.cases WHERE id = :id"), {"id": case_id})
    ).scalar_one_or_none()
    return row is not None


async def _simulation_for_case(
    db: AsyncSession, simulation_id: str | None, case_id: str
) -> dict | None:
    """Return {id, user_attestation} for a linked simulation, latest fallback."""
    if simulation_id:
        row = (
            await db.execute(
                text(
                    "SELECT id, user_attestation FROM public.simulations"
                    " WHERE id = :s AND case_id = :c"
                ),
                {"s": simulation_id, "c": case_id},
            )
        ).mappings().first()
        if row is None:
            raise HTTPException(
                status_code=404, detail="simulation not found for this case"
            )
        return dict(row)
    row = (
        await db.execute(
            text(
                "SELECT id, user_attestation FROM public.simulations"
                " WHERE case_id = :c ORDER BY created_at DESC LIMIT 1"
            ),
            {"c": case_id},
        )
    ).mappings().first()
    return dict(row) if row else None


# ---------- Feature 4: uploads ----------


@router.post(
    "/cases/{case_id}/documents",
    status_code=201,
    dependencies=[Depends(rate_limit("upload", 30, 60))],
)
async def upload_document(
    case_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not await _case_exists(db, case_id):
        raise HTTPException(status_code=404, detail="case not found")

    settings = get_settings()
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds {settings.max_upload_bytes // (1024 * 1024)} MB limit",
        )
    try:
        saved = save_upload(
            case_id, file.filename or "upload", file.content_type, content
        )
    except UploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    extraction_error = None
    try:
        extracted = extract_text(saved["path"], saved["mime_type"])
    except Exception:  # a corrupt file must not lose the upload record
        logger.exception("text extraction failed for %s", saved["path"])
        extracted = ""
        extraction_error = "text extraction failed"

    row = (
        await db.execute(
            text(
                "INSERT INTO public.documents"
                " (case_id, file_path, file_type, original_filename, mime_type,"
                "  size_bytes, sha256, extracted_text)"
                " VALUES (:c, :p, :ft, :fn, :mt, :sz, :sha, :txt)"
                " RETURNING id, uploaded_at"
            ),
            {
                "c": case_id,
                "p": saved["path"],
                "ft": saved["mime_type"],
                "fn": saved["filename"],
                "mt": saved["mime_type"],
                "sz": saved["size_bytes"],
                "sha": saved["sha256"],
                "txt": extracted,
            },
        )
    ).mappings().first()
    if row is None:  # INSERT ... RETURNING must yield a row
        raise HTTPException(status_code=500, detail="upload record was not created")
    await db.commit()
    return {
        "id": str(row["id"]),
        "case_id": case_id,
        "filename": saved["filename"],
        "mime_type": saved["mime_type"],
        "size_bytes": saved["size_bytes"],
        "sha256": saved["sha256"],
        "extracted_chars": len(extracted),
        "extraction_error": extraction_error,
        "uploaded_at": row["uploaded_at"].isoformat() if row["uploaded_at"] else None,
    }


@router.get("/cases/{case_id}/documents")
async def list_uploaded_documents(case_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT id, original_filename, mime_type, size_bytes, sha256,"
                " left(extracted_text, 2000) AS extracted_preview, uploaded_at"
                " FROM public.documents WHERE case_id = :c ORDER BY uploaded_at DESC"
            ),
            {"c": case_id},
        )
    ).mappings().all()
    return [
        {
            **{k: r[k] for k in ("original_filename", "mime_type", "size_bytes", "sha256", "extracted_preview")},
            "id": str(r["id"]),
            "uploaded_at": r["uploaded_at"].isoformat() if r["uploaded_at"] else None,
        }
        for r in rows
    ]


@router.get("/cases/{case_id}/documents/{document_id}")
async def get_uploaded_document(
    case_id: str, document_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    row = (
        await db.execute(
            text(
                "SELECT id, original_filename, mime_type, size_bytes, sha256,"
                " extracted_text, uploaded_at FROM public.documents"
                " WHERE id = :d AND case_id = :c"
            ),
            {"d": document_id, "c": case_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    return {
        **dict(row),
        "id": str(row["id"]),
        "uploaded_at": row["uploaded_at"].isoformat() if row["uploaded_at"] else None,
    }


# ---------- Feature 4b: generated documents ----------


class DocGenerateBody(BaseModel):
    case_id: str
    doc_type: str
    jurisdiction: str
    fields: dict
    verify: bool = True  # run citation verification over `fields` text values
    simulation_id: str | None = None


@router.post(
    "/documents/generate",
    dependencies=[Depends(rate_limit("generate", 30, 60))],
)
async def generate_document(
    body: DocGenerateBody, db: AsyncSession = Depends(get_db)
) -> dict:
    doc_type = require_allowed_doc_type(body.doc_type)  # G3: 422 on prohibited
    if not await _case_exists(db, body.case_id):
        raise HTTPException(status_code=404, detail="case not found (or not yours)")

    cite_rows: list[dict] = []
    if body.verify:
        text_blob = "\n".join(
            str(v) for v in body.fields.values() if isinstance(v, (str, list, dict))
        )
        findings = await verify_citations(text_blob)
        cite_rows = [_finding_dict(f) for f in findings]
    content = render_document(
        doc_type.value, body.jurisdiction, body.fields, citations=cite_rows
    )

    linked = await _simulation_for_case(db, body.simulation_id, body.case_id)
    citations_verified = bool(cite_rows) and all(
        c["status"] == "verified" for c in cite_rows
    )
    export_ready = citations_verified and linked is not None and bool(
        linked.get("user_attestation")
    )

    r = await db.execute(
        text(
            """INSERT INTO public.generated_documents
                 (case_id, simulation_id, doc_type, content, citations,
                  user_reviewed, exported, export_blocked_reason)
               VALUES (:c, :s, :t, :ct, CAST(:cv AS jsonb), false, false, :reason)
               RETURNING id"""
        ),
        {
            "c": body.case_id,
            "s": str(linked["id"]) if linked else None,
            "t": doc_type.value,
            "ct": content,
            "cv": json.dumps(cite_rows),
            "reason": None
            if export_ready
            else "citations/attestation/review gates not all satisfied (SC Gen 23 para 17)",
        },
    )
    doc_id = r.scalar_one()
    await db.commit()
    return {
        "id": str(doc_id),
        "doc_type": doc_type.value,
        "content": content,
        "citations": cite_rows,
        "simulation_id": str(linked["id"]) if linked else None,
        "export_ready": export_ready,
        "gates": {
            "citations_all_verified": citations_verified,
            "simulation_linked": linked is not None,
            "simulation_attested": bool(linked and linked.get("user_attestation")),
            "user_reviewed": False,
        },
        "next_step": (
            "review and verify citations, attest the simulation, then attest this "
            "document, then export"
        ),
    }


@router.get("/cases/{case_id}/generated-documents")
async def list_generated_documents(
    case_id: str, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT id, doc_type, citations, user_reviewed, exported,"
                " export_blocked_reason, created_at FROM public.generated_documents"
                " WHERE case_id = :c ORDER BY created_at DESC"
            ),
            {"c": case_id},
        )
    ).mappings().all()
    return [
        {
            **dict(r),
            "id": str(r["id"]),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


@router.get("/documents/{doc_id}")
async def get_generated_document(doc_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = (
        await db.execute(
            text(
                "SELECT id, case_id, simulation_id, doc_type, content, citations,"
                " user_reviewed, exported, export_blocked_reason, created_at"
                " FROM public.generated_documents WHERE id = :id"
            ),
            {"id": doc_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    return {
        **dict(row),
        "id": str(row["id"]),
        "case_id": str(row["case_id"]),
        "simulation_id": str(row["simulation_id"]) if row["simulation_id"] else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


class AttestBody(BaseModel):
    user_reviewed: bool = True


@router.post("/documents/{doc_id}/attest")
async def attest_document(
    doc_id: str, body: AttestBody, db: AsyncSession = Depends(get_db)
) -> dict:
    if not body.user_reviewed:
        raise HTTPException(status_code=422, detail="user_reviewed must be true to attest")
    current = (
        await db.execute(
            text(
                "SELECT citations, exported, simulation_id"
                " FROM public.generated_documents WHERE id = :id"
            ),
            {"id": doc_id},
        )
    ).mappings().first()
    if current is None:
        raise HTTPException(status_code=404, detail="document not found")
    if current["exported"]:
        raise HTTPException(status_code=409, detail="document already exported")
    if current["simulation_id"] is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "document has no linked simulation — run a simulation first;"
                " SC Gen 23 attestation attaches to the simulation"
            ),
        )
    rows = current["citations"] or []
    unverified = [c for c in rows if c.get("status") != "verified"]
    if unverified:
        raise HTTPException(
            status_code=409,
            detail=f"{len(unverified)} citation(s) unverified — verify before attesting (SC Gen 23 para 17)",
        )
    await db.execute(
        text(
            "UPDATE public.generated_documents SET user_reviewed = true"
            " WHERE id = :id RETURNING id"
        ),
        {"id": doc_id},
    )
    await db.commit()
    return {
        "id": doc_id,
        "user_reviewed": True,
        "citations_all_verified": True,
        "simulation_id": str(current["simulation_id"]),
    }


@router.get("/documents/{doc_id}/export")
async def export_document(
    doc_id: str,
    format: str = Query(default="docx", pattern="^(txt|docx|pdf)$"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = (
        await db.execute(
            text(
                """SELECT id, case_id, simulation_id, doc_type, content, citations,
                          user_reviewed, exported
                   FROM public.generated_documents WHERE id = :id"""
            ),
            {"id": doc_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    if row["exported"]:
        raise HTTPException(status_code=409, detail="document already exported")

    rows = row["citations"] or []
    unverified = [c for c in rows if c.get("status") != "verified"]
    if unverified:
        raise HTTPException(
            status_code=403,
            detail=f"export blocked: {len(unverified)} citation(s) not verified (SC Gen 23 para 17)",
        )
    if not row["user_reviewed"]:
        raise HTTPException(
            status_code=403, detail="export blocked: user has not reviewed the document"
        )
    if row["simulation_id"] is None:
        raise HTTPException(
            status_code=403,
            detail="export blocked: document has no linked simulation (SC Gen 23 attestation)",
        )
    attached = (
        await db.execute(
            text(
                "SELECT user_attestation FROM public.simulations WHERE id = :s"
            ),
            {"s": str(row["simulation_id"])},
        )
    ).scalar_one_or_none()
    if attached is not True:
        raise HTTPException(
            status_code=403,
            detail="export blocked: simulation attestation missing (SC Gen 23)",
        )

    try:
        payload, media_type = export_bytes(row["content"], format)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    await db.execute(
        text(
            "UPDATE public.generated_documents"
            " SET exported = true, export_blocked_reason = NULL"
            " WHERE id = :id RETURNING id"
        ),
        {"id": doc_id},
    )
    await db.commit()
    filename = f"{row['doc_type']}-{str(row['id'])[:8]}.{format}"
    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Document-Id": str(row["id"]),
        },
    )


# ---------- Feature 4c: citations ----------


@router.post(
    "/citations/verify",
    dependencies=[Depends(rate_limit("citations", 60, 60))],
)
async def verify(body: dict, db: AsyncSession = Depends(get_db)) -> dict:
    text_blob = str(body.get("text", ""))[:200_000]
    result = await verify_citations(text_blob)
    return {"citations": [_finding_dict(f) for f in result]}


# ---------- Feature 5: deadlines ----------


class DeadlineBody(BaseModel):
    doc_type: str
    jurisdiction: str
    served_on: date | None = None


@router.post("/deadlines/compute")
async def compute(body: DeadlineBody, db: AsyncSession = Depends(get_db)) -> dict:
    result = compute_deadline(body.doc_type, body.jurisdiction, body.served_on)
    if result is None:
        raise HTTPException(
            status_code=422,
            detail=f"no deadline rule for {body.doc_type} in {body.jurisdiction}",
        )
    due, respond = result
    return {"due_date": due.isoformat(), "respond_doc": respond, "disclaimer": disclaimer()}


@router.post("/cases/{case_id}/deadlines", status_code=201)
async def store_deadline(
    case_id: str, body: DeadlineBody, db: AsyncSession = Depends(get_db)
) -> dict:
    if not await _case_exists(db, case_id):
        raise HTTPException(status_code=404, detail="case not found")
    result = compute_deadline(body.doc_type, body.jurisdiction, body.served_on)
    if result is None:
        raise HTTPException(
            status_code=422,
            detail=f"no deadline rule for {body.doc_type} in {body.jurisdiction}",
        )
    due, respond = result
    row = (
        await db.execute(
            text(
                "INSERT INTO public.deadlines (case_id, trigger_doc_type, due_date)"
                " VALUES (:c, :t, :d) RETURNING id, reminder_sent"
            ),
            {"c": case_id, "t": body.doc_type, "d": due},
        )
    ).mappings().first()
    if row is None:  # INSERT ... RETURNING must yield a row
        raise HTTPException(status_code=500, detail="deadline was not created")
    await db.commit()
    return {
        "id": str(row["id"]),
        "case_id": case_id,
        "trigger_doc_type": body.doc_type,
        "respond_doc": respond,
        "due_date": due.isoformat(),
        "reminder_sent": row["reminder_sent"],
        "disclaimer": disclaimer(),
    }


@router.get("/cases/{case_id}/deadlines")
async def list_deadlines(case_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT id, trigger_doc_type, due_date, reminder_sent, created_at"
                " FROM public.deadlines WHERE case_id = :c ORDER BY due_date"
            ),
            {"c": case_id},
        )
    ).mappings().all()
    return [
        {
            **{k: r[k] for k in ("trigger_doc_type", "reminder_sent")},
            "id": str(r["id"]),
            "due_date": r["due_date"].isoformat(),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


class LimitationBody(BaseModel):
    cause_of_action: str
    jurisdiction: str
    accrual_on: date | None = None


@router.post("/limitations/compute")
async def limitation(body: LimitationBody, db: AsyncSession = Depends(get_db)) -> dict:
    result = compute_limitation(body.cause_of_action, body.jurisdiction, body.accrual_on)
    if result is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"no limitation rule for {body.cause_of_action!r} in"
                f" {body.jurisdiction!r} — verify against the relevant statute"
            ),
        )
    return result


# ---------- Account ----------


@router.get("/users/me")
async def me(db: AsyncSession = Depends(get_db)) -> dict:
    row = (
        await db.execute(
            text(
                "SELECT id, email, role, subscription_tier, created_at"
                " FROM public.users"
                " WHERE id = (current_setting('request.jwt.claims', true)::jsonb ->> 'sub')::uuid"
            )
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="user not found")
    return {
        **dict(row),
        "id": str(row["id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


# ---------- Feature 6: billing ----------


class CheckoutBody(BaseModel):
    plan: str = Field(min_length=2, max_length=80)


@router.get("/billing/plans")
async def plans() -> list[dict]:
    return [
        {
            "id": p.id,
            "label": p.label,
            "amount_cents": p.amount_cents,
            "currency": p.currency,
            "interval": p.interval,
        }
        for p in PLANS.values()
    ]


@router.post(
    "/billing/checkout",
    dependencies=[Depends(rate_limit("billing", 10, 60))],
)
async def checkout(body: CheckoutBody, db: AsyncSession = Depends(get_db)) -> dict:
    sub = (
        await db.execute(
            text("SELECT current_setting('request.jwt.claims', true)::jsonb ->> 'sub'")
        )
    ).scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=401, detail="no verified identity on the session")
    try:
        return await create_checkout_session(
            user_id=str(sub), email=db.info.get("user_email"), plan_id=body.plan
        )
    except KeyError:
        raise HTTPException(status_code=422, detail=f"unknown plan '{body.plan}'") from None
    except BillingUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@router.post("/billing/webhook")
async def billing_webhook(request: Request) -> dict:
    """Stripe webhook — authenticated by signature, not by a user JWT."""
    payload = await request.body()
    try:
        event = verify_webhook(payload, request.headers.get("stripe-signature"))
    except BillingUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except WebhookError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    entitlement = entitlement_from_event(event)
    if entitlement is None:
        return {"received": True, "handled": False}
    user_id, plan_id = entitlement

    async with SessionFactory() as session:
        await session.execute(text("SET LOCAL search_path = public, auth"))
        await session.execute(
            text("UPDATE public.users SET subscription_tier = :p WHERE id = :u"),
            {"p": plan_id, "u": user_id},
        )
        await session.commit()
    return {"received": True, "handled": True, "plan": plan_id}
