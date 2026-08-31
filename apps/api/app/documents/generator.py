"""Document generation (feature 4b) + C5 export gate + G3 hard block.

Templates are deliberately conservative: chronology, correspondence, submissions.
SC Gen 23 para 10/20 prohibited types never leave `require_allowed_doc_type`.
The AI-disclosure footer is appended server-side — templates cannot omit it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from jinja2 import Environment

DISCLOSURE_FOOTER = (
    "This document was prepared with AI assistance (LexSim AI). "
    "It does not replace legal advice. You remain responsible for all court filings "
    "and must verify every citation against an authoritative source before filing."
)


def _env() -> Environment:
    env = Environment(autoescape=True)  # autoescape: docs are filed, escape user input
    env.globals["today"] = datetime.now(UTC).strftime("%-d %B %Y")
    return env


_TEMPLATES: dict[str, str] = {
    "statement_of_claim": (
        "IN THE {{ jurisdiction|upper }}\n\nBETWEEN:\n\n{{ plaintiff }} (Plaintiff)\n\nAND:\n\n{{ defendant }} (Defendant)\n\n"
        "STATEMENT OF CLAIM\n\nFiled: {{ today }}\n\n1. {{ party_opening }}\n\n"
        "{% for para in facts %}{{ loop.index + 1 }}. {{ para }}\n{% endfor %}\n"
        "{% for cause in causes_of_action %}AND the Plaintiff claims: {{ cause }}\n{% endfor %}"
    ),
    "defence": (
        "IN THE {{ jurisdiction|upper }}\n\nBETWEEN:\n\n{{ plaintiff }} (Plaintiff) and {{ defendant }} (Defendant)\n\n"
        "DEFENCE\n\nFiled: {{ today }}\n\n1. {{ party_opening }}\n\n"
        "{% for para in defences %}{{ loop.index + 1 }}. {{ para }}\n{% endfor %}"
    ),
    "written_submissions": (
        "IN THE {{ jurisdiction|upper }}\n\nBETWEEN:\n\n{{ plaintiff }} (Plaintiff) and {{ defendant }} (Defendant)\n\n"
        "PLAINTIFF'S WRITTEN SUBMISSIONS\n\nFiled: {{ today }}\n\n"
        "A. Introduction\n{% for para in submissions %}\n{{ para }}{% endfor %}\n\nB. Orders sought\n{{ orders }}"
    ),
    "chronology": (
        "CHRONOLOGY OF EVENTS\n\nMatter: {{ matter }}\nJurisdiction: {{ jurisdiction|upper }}\nPrepared: {{ today }}\n\n"
        "{% for e in events %}{{ e.date }}  —  {{ e.event }}{% if e.source %} ({{ e.source }}){% endif %}\n{% endfor %}"
    ),
    "court_correspondence": (
        "To: {{ recipient }}\nFrom: {{ sender }}\nDate: {{ today }}\nRe: {{ matter }}\n\n{{ body }}\n\nYours faithfully,\n{{ sender }}"
    ),
}


def render_document(
    doc_type: str,
    jurisdiction: str,
    fields: dict,
    citations: list[dict] | None = None,
) -> str:
    """Render an already-allowed doc type (caller must have run require_allowed_doc_type)."""
    template = _TEMPLATES.get(doc_type)
    if template is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail=f"Unknown document type '{doc_type}'.")
    body = _env().from_string(template).render(jurisdiction=jurisdiction, **fields)
    citation_table = ""
    if citations:
        rows = "\n".join(
            f"  {c.get('raw','?')} — {c.get('status','unverified').upper()}" for c in citations
        )
        citation_table = f"\n\nCITATION VERIFICATION RECORD\n{rows}\n"
    return body + citation_table + f"\n\n{DISCLOSURE_FOOTER}\n"


def citation_gate_status(doc: dict) -> tuple[bool, str]:
    """C5: export allowed only when every citation row verified AND user_reviewed
    AND simulation-level user_attestation. Returns (allowed, reason)."""
    rows = doc.get("citations") or []
    unverified = [r for r in rows if r.get("status") != "verified"]
    if unverified:
        return False, f"{len(unverified)} citation(s) not verified"
    if not doc.get("user_reviewed"):
        return False, "user has not reviewed the document"
    if not doc.get("user_attestation"):
        return False, "user has not attested to AI-content review (SC Gen 23)"
    return True, "ok"