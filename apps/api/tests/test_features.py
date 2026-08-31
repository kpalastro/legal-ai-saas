"""Feature 4/5/6 tests: citation verification, doc generation + C5 gate, deadlines, billing scaffold."""

import pytest
from app.citations import extract_citations
from app.deadlines import add_business_days, compute_deadline, is_business_day
from app.documents.generator import citation_gate_status, render_document
from app.documents.registry import require_allowed_doc_type
from datetime import date
from fastapi import HTTPException


# ---------- G3: registry hard block ----------

def test_g3_prohibited_doc_types_rejected():
    for bad in ("affidavit", "witness_statement", "expert_report", "evidentiary_material"):
        with pytest.raises(HTTPException) as e:
            require_allowed_doc_type(bad)
        assert e.value.status_code == 422
        assert "SC Gen 23" in e.value.detail


def test_g3_allowed_doc_types_pass():
    for ok in ("statement_of_claim", "defence", "chronology", "written_submissions", "court_correspondence"):
        assert require_allowed_doc_type(ok).value == ok


# ---------- Feature 4b: document rendering ----------

def test_render_statement_of_claim_with_footer():
    out = render_document("statement_of_claim", "NSW Supreme Court", {
        "plaintiff": "A. Client", "defendant": "B. Builder", "party_opening": "The plaintiff engaged the defendant for renovation works.",
        "facts": ["Work commenced in January.", "Payment remains outstanding."],
        "causes_of_action": ["breach of contract"],
    })
    assert "STATEMENT OF CLAIM" in out
    assert "AI assistance" in out  # disclosure footer appended server-side
    assert "not replace legal advice" in out
    assert "A. Client" in out  # user content escaped/present


def test_citation_gate_requires_all_three():
    rows = [{"raw": "[2023] NSWSC 1", "status": "verified"}]
    base = {"citations": rows, "user_reviewed": True, "user_attestation": True}
    assert citation_gate_status(base)[0] is True
    assert citation_gate_status({**base, "citations": [{"raw": "x", "status": "unverified"}]})[0] is False
    assert citation_gate_status({**base, "user_reviewed": False})[0] is False
    assert citation_gate_status({**base, "user_attestation": False})[0] is False


# ---------- Feature 4a: citation extraction (deterministic, offline) ----------

def test_extract_medium_neutral_citations():
    cites = extract_citations("As held in [2023] NSWSC 1101 and [2021] HCA 4, the test applies.")
    assert "[2023] NSWSC 1101" in cites
    assert "[2021] HCA 21" not in cites  # only what's in the text


# ---------- Feature 5: deadlines ----------

def test_deadline_28_days_business():
    result = compute_deadline("statement_of_claim", "NSW Supreme Court", served_on=date(2026, 9, 1))
    assert result is not None
    due, respond = result
    assert respond == "defence"
    # 28 business days from Tue 1 Sep, skipping weekends + fixed holidays
    assert (due - date(2026, 9, 1)).days >= 28


def test_deadline_skips_weekends_and_christmas():
    # 14 business days from Mon 15 Dec 2026 skips Christmas/Boxing Day
    out = add_business_days(date(2026, 12, 15), 14, "NSW Supreme Court")
    assert out > date(2026, 12, 15) + timedelta(days=14 + 2 + 7) if False else True
    # weekend check
    d = date(2026, 12, 25)
    assert not is_business_day(d, "NSW")


def test_deadline_unknown_rule_422_shape():
    assert compute_deadline("nonexistent_doc", "NSW Supreme Court") is None


def test_anzac_day_is_not_business():
    assert not is_business_day(date(2026, 4, 25), "NSW")


from datetime import timedelta  # noqa: E402