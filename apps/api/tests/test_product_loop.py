"""End-to-end product-loop tests (auth -> intake -> upload -> debate -> attest -> export).

These use the real FastAPI app over httpx's ASGI transport and a real Postgres,
with a deterministic stub LLM (TEST_PLAN: tests never depend on live inference).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.agents.prompts import PROMPT_VERSION, parse_weakness_report, verdict_from_text
from app.citations.service import CitationFinding, CitationStatus
from app.config import get_settings
from app.db import SessionFactory, arm_request
from app.documents.exporters import to_docx, to_pdf
from app.documents.storage import UploadError, validate_upload
from app.llm.base import LLMResponse
from app.main import app
from app.ratelimit import consume_memory


class StubProvider:
    """Deterministic 9-turn provider; records prompts for grounding assertions."""

    model = "stub:test"

    def __init__(self) -> None:
        self.requests: list[str] = []

    async def complete(self, req):
        self.requests.append(req.user)
        return LLMResponse(
            text='{"lower": 40, "point": 50, "upper": 60}',
            model=self.model,
            prompt_tokens=1,
            completion_tokens=1,
        )

    async def health(self) -> bool:
        return True

    async def warmup(self) -> None:
        return None


@pytest.fixture
def settings():
    return get_settings()


@pytest_asyncio.fixture
async def api():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def user(api):
    sub = str(uuid.uuid4())
    token = jwt.encode(
        {
            "sub": sub,
            "role": "authenticated",
            "aud": "",
            "exp": int(time.time()) + 3600,
        },
        get_settings().supabase_jwt_secret,
        algorithm="HS256",
    )
    yield {"id": sub, "token": token, "headers": {"Authorization": f"Bearer {token}"}}

    # Use a dedicated engine for cleanup: the app's global pool can still have a
    # connection finishing SSE finalisation, and sharing it races asyncpg.
    import asyncio
    import shutil

    from sqlalchemy.ext.asyncio import create_async_engine

    await asyncio.sleep(0)
    cleanup = create_async_engine(get_settings().database_url)
    try:
        async with cleanup.begin() as conn:
            await conn.execute(text("SET LOCAL session_replication_role = replica"))
            await conn.execute(
                text("DELETE FROM public.audit_log WHERE user_id = :u"), {"u": sub}
            )
            await conn.execute(text("SET LOCAL session_replication_role = DEFAULT"))
            await conn.execute(
                text("DELETE FROM public.cases WHERE user_id = :u"), {"u": sub}
            )
            await conn.execute(text("DELETE FROM public.users WHERE id = :u"), {"u": sub})
            try:
                await conn.execute(text("DELETE FROM auth.users WHERE id = :u"), {"u": sub})
            except Exception:
                pass
    finally:
        await cleanup.dispose()
    shutil.rmtree("/tmp/lexsim-test-storage", ignore_errors=True)


@pytest_asyncio.fixture
async def case(api, user):
    response = await api.post(
        "/cases",
        headers=user["headers"],
        json={
            "title": "[TEST] contract dispute",
            "jurisdiction": "NSW Supreme Court",
            "cause_of_action": "contract_breach",
            "description": "A written contract was signed and the defendant failed to pay.",
            "parties": [{"name": "A. Plaintiff", "role": "plaintiff"}],
            "issues": ["Was there a breach of contract?"],
            "relief_sought": "Damages of $50,000",
            "court": "NSW Supreme Court",
            "case_number": "2026/001234",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _frames(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.split("\n\n"):
        event = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                data = line[6:]
        if event and data:
            out.append((event, json.loads(data)))
    return out


async def _run_sim(api, user, case_id, monkeypatch, provider=None):
    provider = provider or StubProvider()
    import app.llm as llm_module

    monkeypatch.setattr(llm_module, "get_provider", lambda: provider)
    response = await api.get(f"/cases/{case_id}/simulate", headers=user["headers"])
    assert response.status_code == 200, response.text
    frames = _frames(response.text)
    turns = [p for e, p in frames if e == "turn"]
    done = next((p for e, p in frames if e == "done"), None)
    assert len(turns) == 9, f"expected 9 turns, got {len(turns)}"
    assert done is not None, response.text
    return provider, done


# ---------- intake + grounding ----------


async def test_case_detail_and_update(api, user, case):
    response = await api.get(f"/cases/{case}", headers=user["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["description"].startswith("A written contract")
    assert body["issues"] == ["Was there a breach of contract?"]
    assert body["document_count"] == 0

    response = await api.patch(
        f"/cases/{case}",
        headers=user["headers"],
        json={"issues": ["Was there a breach?", "What loss flowed?"]},
    )
    assert response.status_code == 200
    response = await api.get(f"/cases/{case}", headers=user["headers"])
    assert response.json()["issues"] == ["Was there a breach?", "What loss flowed?"]


async def test_upload_is_extracted_and_grounds_the_debate(api, user, case, monkeypatch):
    response = await api.post(
        f"/cases/{case}/documents",
        headers=user["headers"],
        files={
            "file": (
                "facts.txt",
                b"The defendant admitted the debt in writing on 3 March 2026.",
                "text/plain",
            )
        },
    )
    assert response.status_code == 201, response.text
    uploaded = response.json()
    assert uploaded["extracted_chars"] > 0

    listing = await api.get(f"/cases/{case}/documents", headers=user["headers"])
    assert len(listing.json()) == 1
    assert "admitted the debt" in listing.json()[0]["extracted_preview"]

    provider, done = await _run_sim(api, user, case, monkeypatch)
    # Grounding: the first prompt contains the intake facts, issues and upload text.
    first = provider.requests[0]
    assert "The defendant admitted the debt" in first
    assert "Was there a breach of contract?" in first
    assert "Damages of $50,000" in first
    # Statefulness: turn 2 sees turn 1 (the old engine sent no transcript).
    assert "Turn 1" in provider.requests[1]

    detail = await api.get(f"/cases/{case}", headers=user["headers"])
    assert detail.json()["status"] == "completed"
    assert detail.json()["simulation_count"] == 1
    assert done["verdict"]["lower"] == 40


async def test_audit_is_committed_per_turn_even_when_the_run_fails(api, user, case):
    from app.agents.engine import run_debate

    class FailOnSecondTurn(StubProvider):
        async def complete(self, req):
            if self.requests:
                raise RuntimeError("provider failed on turn 2")
            return await super().complete(req)

    async with SessionFactory() as session:
        await arm_request(session, user_id=user["id"])
        with pytest.raises(RuntimeError):
            await run_debate(
                session, case_id=case, user_id=user["id"], provider=FailOnSecondTurn()
            )

    async with SessionFactory() as session:
        await session.execute(text("SET LOCAL search_path = public, auth"))
        rows = (
            await session.execute(
                text("SELECT count(*) FROM public.audit_log WHERE case_id = :c"),
                {"c": case},
            )
        ).scalar()
    assert rows == 1, "turn-1 audit must survive a turn-2 failure (C1/G5 durability)"


# ---------- attestation + export ----------


async def test_document_gate_attestation_and_export(api, user, case, monkeypatch):
    _, done = await _run_sim(api, user, case, monkeypatch)
    simulation_id = done["simulation_id"]

    async def fake_verify(text, client=None):
        return [
            CitationFinding(
                "[2023] NSWSC 1",
                CitationStatus.VERIFIED,
                "nsw_caselaw",
                "https://nsw.caselaw.example/1",
                "2026-11-19T00:00:00+00:00",
                "R v Example [2023] NSWSC 1",
            )
        ]

    monkeypatch.setattr("app.routers.features.verify_citations", fake_verify)
    response = await api.post(
        "/documents/generate",
        headers=user["headers"],
        json={
            "case_id": case,
            "doc_type": "statement_of_claim",
            "jurisdiction": "NSW Supreme Court",
            "fields": {
                "plaintiff": "A. Plaintiff",
                "defendant": "B. Defendant",
                "party_opening": "The plaintiff relies on [2023] NSWSC 1.",
                "facts": ["A contract was signed."],
                "causes_of_action": ["breach of contract"],
            },
        },
    )
    assert response.status_code == 200, response.text
    doc = response.json()
    assert doc["simulation_id"] == simulation_id
    assert doc["gates"]["simulation_linked"] is True
    assert doc["gates"]["simulation_attested"] is False
    assert doc["gates"]["citations_all_verified"] is True

    snapshots = await api.get(
        f"/cases/{case}/authority-snapshots", headers=user["headers"]
    )
    assert snapshots.status_code == 200
    assert len(snapshots.json()) == 1
    assert snapshots.json()[0]["status"] == "verified"
    assert snapshots.json()[0]["content_sha256"]

    # Export is blocked until the simulation is attested.
    blocked = await api.get(
        f"/documents/{doc['id']}/export?format=txt", headers=user["headers"]
    )
    assert blocked.status_code == 403

    attested = await api.post(
        f"/simulations/{simulation_id}/attest",
        headers=user["headers"],
        json={"user_attestation": True},
    )
    assert attested.status_code == 200
    assert attested.json()["user_attestation"] is True

    # Still blocked until the document itself is reviewed/attested.
    blocked = await api.get(
        f"/documents/{doc['id']}/export?format=txt", headers=user["headers"]
    )
    assert blocked.status_code == 403

    reviewed = await api.post(
        f"/documents/{doc['id']}/attest",
        headers=user["headers"],
        json={"user_reviewed": True},
    )
    assert reviewed.status_code == 200

    signed = await api.post(
        f"/documents/{doc['id']}/sign",
        headers=user["headers"],
        json={"signer_name": "A. Plaintiff"},
    )
    assert signed.status_code == 200, signed.text
    signature = await api.get(
        f"/documents/{doc['id']}/signature", headers=user["headers"]
    )
    assert signature.json()["signer_name"] == "A. Plaintiff"

    versions = await api.get(
        f"/documents/{doc['id']}/versions", headers=user["headers"]
    )
    assert versions.status_code == 200
    assert versions.json()[0]["version"] == 1

    exported = await api.get(
        f"/documents/{doc['id']}/export?format=txt", headers=user["headers"]
    )
    assert exported.status_code == 200, exported.text
    assert "AI assistance" in exported.text
    assert "attachment; filename=" in exported.headers["content-disposition"]
    assert exported.headers["x-document-signer"] == "A. Plaintiff"

    again = await api.get(
        f"/documents/{doc['id']}/export?format=txt", headers=user["headers"]
    )
    assert again.status_code == 409


async def test_document_revision_supersedes_and_exports(api, user, case, monkeypatch):
    _, done = await _run_sim(api, user, case, monkeypatch)
    simulation_id = done["simulation_id"]
    await api.post(
        f"/simulations/{simulation_id}/attest",
        headers=user["headers"],
        json={"user_attestation": True},
    )
    first = await api.post(
        "/documents/generate",
        headers=user["headers"],
        json={
            "case_id": case,
            "doc_type": "written_submissions",
            "jurisdiction": "NSW Supreme Court",
            "verify": False,
            "fields": {
                "plaintiff": "A",
                "defendant": "B",
                "party_opening": "Opening",
                "submissions": ["First submission."],
                "orders": "Orders sought.",
            },
        },
    )
    assert first.status_code == 200, first.text
    original = first.json()
    await api.post(
        f"/documents/{original['id']}/attest",
        headers=user["headers"],
        json={"user_reviewed": True},
    )

    revised = await api.post(
        f"/documents/{original['id']}/revise",
        headers=user["headers"],
        json={
            "verify": False,
            "fields": {
                "plaintiff": "A",
                "defendant": "B",
                "party_opening": "Opening (revised)",
                "submissions": ["Revised submission."],
                "orders": "Orders sought.",
            },
        },
    )
    assert revised.status_code == 200, revised.text
    new_doc = revised.json()
    assert new_doc["version"] == 2
    assert new_doc["supersedes_id"] == original["id"]

    diff = await api.get(
        f"/documents/{new_doc['id']}/diff", headers=user["headers"]
    )
    assert diff.status_code == 200, diff.text
    assert "Revised submission" in diff.json()["diff"]
    assert diff.json()["to_version"] == 2

    comment = await api.post(
        f"/documents/{new_doc['id']}/comments",
        headers=user["headers"],
        json={"body": "Check the prayer for relief."},
    )
    assert comment.status_code == 201, comment.text
    comments = await api.get(
        f"/documents/{new_doc['id']}/comments", headers=user["headers"]
    )
    assert len(comments.json()) == 1
    resolved = await api.patch(
        f"/comments/{comment.json()['id']}",
        headers=user["headers"],
        json={"resolved": True},
    )
    assert resolved.status_code == 200 and resolved.json()["resolved"] is True
    deleted = await api.delete(
        f"/comments/{comment.json()['id']}", headers=user["headers"]
    )
    assert deleted.status_code == 200

    old = await api.get(f"/documents/{original['id']}", headers=user["headers"])
    assert old.json()["superseded"] is True
    blocked = await api.get(
        f"/documents/{original['id']}/export?format=txt", headers=user["headers"]
    )
    assert blocked.status_code == 409

    await api.post(
        f"/documents/{new_doc['id']}/attest",
        headers=user["headers"],
        json={"user_reviewed": True},
    )
    exported = await api.get(
        f"/documents/{new_doc['id']}/export?format=txt", headers=user["headers"]
    )
    assert exported.status_code == 200
    assert exported.headers["x-document-version"] == "2"


def test_extra_document_types_render():
    from app.documents.generator import render_document

    damages = render_document(
        "schedule_of_damages",
        "NSW Supreme Court",
        {
            "plaintiff": "A",
            "defendant": "B",
            "items": [{"description": "Invoice", "amount": "$10,000"}],
            "total": "$10,000",
        },
    )
    assert "SCHEDULE OF DAMAGES" in damages
    listing = render_document(
        "list_of_documents",
        "NSW Supreme Court",
        {
            "matter": "A v B",
            "documents": [{"date": "2026-01-01", "description": "Contract", "party": "A"}],
        },
    )
    assert "LIST OF DOCUMENTS" in listing


def test_exporters_produce_real_files():
    assert to_docx("hello").startswith(b"PK")
    assert to_pdf("hello").startswith(b"%PDF-")


def test_upload_validation(monkeypatch, settings):
    assert validate_upload("a.txt", "text/plain", b"hello")[0] == "text/plain"
    # Markdown/CSV are UTF-8 text: their content sniff is text/plain.
    assert validate_upload("notes.md", "text/markdown", b"# notes")[0] == "text/markdown"
    assert validate_upload("rows.csv", "text/csv", b"a,b\n1,2")[0] == "text/csv"
    with pytest.raises(UploadError):
        validate_upload("a.pdf", "application/pdf", b"not actually a pdf")
    with pytest.raises(UploadError):
        validate_upload("a.exe", "application/octet-stream", b"MZ")
    monkeypatch.setattr(settings, "max_upload_bytes", 4)
    with pytest.raises(UploadError):
        validate_upload("a.txt", "text/plain", b"too long")


# ---------- deadlines + limitations ----------


async def test_deadlines_are_persisted_and_limitations_computed(api, user, case):
    response = await api.post(
        f"/cases/{case}/deadlines",
        headers=user["headers"],
        json={
            "doc_type": "statement_of_claim",
            "jurisdiction": "NSW Supreme Court",
            "served_on": "2026-11-19",
        },
    )
    assert response.status_code == 201, response.text
    stored = response.json()
    assert stored["respond_doc"] == "defence"
    assert stored["due_date"] > "2026-11-19"

    listing = await api.get(f"/cases/{case}/deadlines", headers=user["headers"])
    assert len(listing.json()) == 1

    response = await api.post(
        "/limitations/compute",
        headers=user["headers"],
        json={
            "cause_of_action": "contract",
            "jurisdiction": "NSW Supreme Court",
            "accrual_on": "2020-01-15",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["due_date"] == "2026-01-15"
    assert "Limitation Act 1969" in response.json()["provision"]

    unknown = await api.post(
        "/limitations/compute",
        headers=user["headers"],
        json={"cause_of_action": "defamation", "jurisdiction": "NSW"},
    )
    assert unknown.status_code == 422


def test_easter_and_public_holidays():
    from app.deadlines.service import easter_sunday, public_holidays

    assert easter_sunday(2026).isoformat() == "2026-04-05"
    nsw = public_holidays(2026, "NSW Supreme Court")
    assert easter_sunday(2026) - timedelta(days=2) in nsw
    assert easter_sunday(2026) + timedelta(days=1) in nsw


# ---------- verdict validation ----------


def test_verdict_is_validated():
    good = verdict_from_text('{"lower": 40, "point": 50, "upper": 60}')
    assert (good["lower"], good["point"], good["upper"]) == (40, 50, 60)
    assert "methodology_note" in good

    misordered = verdict_from_text('{"lower": 70, "point": 50, "upper": 60}')
    assert "raw" in misordered
    out_of_range = verdict_from_text('{"lower": 0, "point": 5000, "upper": 9000}')
    assert "raw" in out_of_range


# ---------- billing ----------


async def test_billing_webhook_verifies_signature_and_grants_tier(
    api, user, case, monkeypatch, settings
):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_secret")
    payload = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": user["id"],
                    "metadata": {"plan": "lawyer_monthly_10"},
                }
            },
        }
    ).encode()
    timestamp = int(time.time())
    signature = hmac.new(
        b"whsec_test_secret", f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()

    response = await api.post(
        "/billing/webhook",
        content=payload,
        headers={
            "content-type": "application/json",
            "stripe-signature": f"t={timestamp},v1={signature}",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["plan"] == "lawyer_monthly_10"

    me = await api.get("/users/me", headers=user["headers"])
    assert me.json()["subscription_tier"] == "lawyer_monthly_10"

    cancellation = json.dumps(
        {
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "metadata": {
                        "user_id": user["id"],
                        "plan": "lawyer_monthly_10",
                    }
                }
            },
        }
    ).encode()
    cancel_ts = int(time.time())
    cancel_sig = hmac.new(
        b"whsec_test_secret", f"{cancel_ts}.".encode() + cancellation, hashlib.sha256
    ).hexdigest()
    cancelled = await api.post(
        "/billing/webhook",
        content=cancellation,
        headers={
            "content-type": "application/json",
            "stripe-signature": f"t={cancel_ts},v1={cancel_sig}",
        },
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["plan"] is None
    downgraded = await api.get("/users/me", headers=user["headers"])
    assert downgraded.json()["subscription_tier"] is None
    assert downgraded.json()["limits"]["cases"] == 2

    bad = await api.post(
        "/billing/webhook",
        content=payload,
        headers={
            "content-type": "application/json",
            "stripe-signature": f"t={timestamp},v1=deadbeef",
        },
    )
    assert bad.status_code == 400


async def test_checkout_is_unavailable_without_stripe(api, user, monkeypatch, settings):
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    response = await api.post(
        "/billing/checkout", headers=user["headers"], json={"plan": "individual_case_full"}
    )
    assert response.status_code == 503


# ---------- misc ----------


async def test_health_reports_rls_posture(api):
    response = await api.get("/health/db")
    assert response.status_code == 200
    body = response.json()
    assert body["app_role"] == get_settings().db_app_role
    assert body["rls_enforced"] is True
    assert "connection_role" in body
    assert body["public_tables"] >= 8


async def test_app_tables_live_in_public_schema():
    """The Nov 2026 dev/CI divergence: tables must not land in the auth schema."""
    async with SessionFactory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT table_schema, table_name FROM information_schema.tables"
                    " WHERE table_schema IN ('public', 'auth')"
                    " AND table_name IN ('cases', 'documents', 'simulations',"
                    "                    'generated_documents', 'deadlines',"
                    "                    'audit_log', 'audit_content')"
                )
            )
        ).all()
    assert rows
    assert all(schema == "public" for schema, _ in rows), rows


async def test_rate_limit_memory_window():
    key = f"unit-{uuid.uuid4().hex}"
    assert (await consume_memory(key, 2, 60))[0] is True
    assert (await consume_memory(key, 2, 60))[0] is True
    allowed, retry = await consume_memory(key, 2, 60)
    assert allowed is False and retry >= 0


# ---------- retrieval, analysis, entitlements, privacy ----------


async def test_retrieval_finds_the_relevant_chunk(api, user, case, monkeypatch):
    # A document much larger than the prompt budget: only retrieval can surface
    # the passage about the issue.
    body = (
        "background material about invoices and payments. " * 200
        + "The breach of contract claim is subject to an arbitration clause. "
        + "MARKER-ARBITRATION-9931. "
        + "unrelated appendix material. " * 500
    ).encode()
    uploaded = await api.post(
        f"/cases/{case}/documents",
        headers=user["headers"],
        files={"file": ("exhibit.txt", body, "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["chunk_count"] > 1

    provider, _ = await _run_sim(api, user, case, monkeypatch)
    assert "MARKER-ARBITRATION-9931" in provider.requests[0]


class AnalysisStub(StubProvider):
    async def complete(self, req):
        self.requests.append(req.user)
        return LLMResponse(
            text=json.dumps(
                {
                    "summary": "The plaintiff's case is vulnerable on causation.",
                    "weaknesses": [
                        {
                            "issue": "Causation",
                            "side": "plaintiff",
                            "severity": "high",
                            "why": "No expert evidence links the loss to the breach.",
                            "evidence_gap": "Expert report",
                            "next_step": "Obtain a causation report.",
                        }
                    ],
                }
            ),
            model=self.model,
            prompt_tokens=1,
            completion_tokens=1,
        )


async def test_weakness_analysis_is_stored_and_audited(api, user, case, monkeypatch):
    _, done = await _run_sim(api, user, case, monkeypatch)
    simulation_id = done["simulation_id"]

    import app.llm as llm_module

    monkeypatch.setattr(llm_module, "get_provider", lambda: AnalysisStub())
    response = await api.post(
        f"/simulations/{simulation_id}/analysis",
        headers=user["headers"],
        json={"verify_citations": False},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["weakness_report"]["weaknesses"][0]["issue"] == "Causation"
    assert body["hallucination_score"] == 0.0

    detail = await api.get(f"/simulations/{simulation_id}", headers=user["headers"])
    assert detail.json()["weakness_report"]["weaknesses"][0]["severity"] == "high"

    async with SessionFactory() as session:
        await session.execute(text("SET LOCAL search_path = public, auth"))
        audit = (
            await session.execute(
                text(
                    "SELECT prompt_version FROM public.audit_log"
                    " WHERE case_id = :c AND event_type = 'simulation_analysis'"
                ),
                {"c": case},
            )
        ).scalars().all()
    assert audit and audit[0] == PROMPT_VERSION


def test_weakness_parser_never_raises():
    parsed = parse_weakness_report('{"summary": "ok", "weaknesses": []}')
    assert parsed["summary"] == "ok"
    assert parsed["weaknesses"] == []
    fallback = parse_weakness_report("not json at all")
    assert fallback["parse_error"] is True
    assert fallback["weaknesses"] == []

    with_settlement = parse_weakness_report(
        json.dumps(
            {
                "summary": "ok",
                "weaknesses": [],
                "settlement": {
                    "range": "$10k–$20k",
                    "factors": ["liability risk"],
                    "cost_risks": ["expert fees"],
                },
            }
        )
    )
    assert with_settlement["settlement"]["range"] == "$10k–$20k"
    assert with_settlement["settlement"]["cost_risks"] == ["expert fees"]


async def test_case_quota_and_upgrade(api, user, case, monkeypatch, settings):
    # Free tier allows 2 cases; the fixture created one.
    second = await api.post(
        "/cases",
        headers=user["headers"],
        json={
            "title": "[TEST] second matter",
            "jurisdiction": "NSW",
            "cause_of_action": "contract",
        },
    )
    assert second.status_code == 201
    third = await api.post(
        "/cases",
        headers=user["headers"],
        json={
            "title": "[TEST] third matter",
            "jurisdiction": "NSW",
            "cause_of_action": "contract",
        },
    )
    assert third.status_code == 402

    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_secret")
    payload = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": user["id"],
                    "metadata": {"plan": "lawyer_monthly_unlimited"},
                }
            },
        }
    ).encode()
    timestamp = int(time.time())
    signature = hmac.new(
        b"whsec_test_secret", f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    upgraded = await api.post(
        "/billing/webhook",
        content=payload,
        headers={
            "content-type": "application/json",
            "stripe-signature": f"t={timestamp},v1={signature}",
        },
    )
    assert upgraded.status_code == 200

    third = await api.post(
        "/cases",
        headers=user["headers"],
        json={
            "title": "[TEST] third matter after upgrade",
            "jurisdiction": "NSW",
            "cause_of_action": "contract",
        },
    )
    assert third.status_code == 201

    me = await api.get("/users/me", headers=user["headers"])
    assert me.json()["limits"]["cases"] is None
    assert me.json()["usage"]["cases"] == 3


async def test_legal_hold_blocks_erasure_then_erase_deidentifies(api, user, case):
    held = await api.post(
        f"/cases/{case}/legal-hold", headers=user["headers"], json={"legal_hold": True}
    )
    assert held.status_code == 200 and held.json()["legal_hold"] is True

    blocked = await api.post(
        "/users/me/erase", headers=user["headers"], json={"confirm": "ERASE"}
    )
    assert blocked.status_code == 409

    released = await api.post(
        f"/cases/{case}/legal-hold", headers=user["headers"], json={"legal_hold": False}
    )
    assert released.status_code == 200

    erased = await api.post(
        "/users/me/erase", headers=user["headers"], json={"confirm": "ERASE"}
    )
    assert erased.status_code == 200, erased.text
    assert erased.json()["cases_deidentified"] == 1
    assert erased.json()["audit_retained"] is True
    assert erased.json()["identity_deleted"] is False  # admin API not configured

    detail = await api.get(f"/cases/{case}", headers=user["headers"])
    assert detail.json()["title"] == "[erased]"
    assert detail.json()["description"] is None
    me = await api.get("/users/me", headers=user["headers"])
    assert me.json()["email"].startswith("erased+")
    assert me.json()["erased_at"] is not None


async def test_export_and_calendar(api, user, case):
    export = await api.get("/users/me/export", headers=user["headers"])
    assert export.status_code == 200
    body = export.json()
    assert body["format_version"] == 1
    assert body["cases"][0]["id"] == case

    await api.post(
        f"/cases/{case}/deadlines",
        headers=user["headers"],
        json={
            "doc_type": "statement_of_claim",
            "jurisdiction": "NSW Supreme Court",
            "served_on": "2026-11-19",
        },
    )
    ics = await api.get(f"/cases/{case}/deadlines.ics", headers=user["headers"])
    assert ics.status_code == 200
    assert "BEGIN:VCALENDAR" in ics.text
    assert "DTSTART;VALUE=DATE:2026" in ics.text


async def test_retention_deidentifies_old_cases_unless_held(user, case):
    from worker.main import retention_sweep

    old = datetime.now(UTC) - timedelta(days=365 * 8)
    async with SessionFactory() as session:
        await session.execute(
            text("UPDATE public.cases SET created_at = :d, legal_hold = TRUE WHERE id = :c"),
            {"d": old, "c": case},
        )
        await session.commit()

    result = await retention_sweep({})
    assert result["erased"] == 0

    async with SessionFactory() as session:
        await session.execute(
            text("UPDATE public.cases SET legal_hold = FALSE WHERE id = :c"), {"c": case}
        )
        await session.commit()

    result = await retention_sweep({})
    assert result["erased"] >= 1

    async with SessionFactory() as session:
        await session.execute(text("SET LOCAL search_path = public, auth"))
        title = (
            await session.execute(
                text("SELECT title FROM public.cases WHERE id = :c"), {"c": case}
            )
        ).scalar_one()
    assert title == "[erased]"
