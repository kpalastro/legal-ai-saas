"""SC Gen 23 hard block (G3): the generator registry contains NO affidavit,
witness-statement, or evidentiary-material template. Selection UI hides them for
AU jurisdictions; the API rejects them here. Do not add them back — SC Gen 23 para 10/20.
"""

from enum import StrEnum

from fastapi import HTTPException


class DocType(StrEnum):
    STATEMENT_OF_CLAIM = "statement_of_claim"
    DEFENCE = "defence"
    WRITTEN_SUBMISSIONS = "written_submissions"
    CHRONOLOGY = "chronology"
    COURT_CORRESPONDENCE = "court_correspondence"


PROHIBITED_DOC_TYPES = frozenset(
    {"affidavit", "witness_statement", "expert_report", "evidentiary_material"}
)


def require_allowed_doc_type(doc_type: str) -> DocType:
    """G3: reject prohibited types with 422 at the API layer."""
    if doc_type.lower() in PROHIBITED_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Document type '{doc_type}' is prohibited under NSW SC Gen 23 para 10/20.",
        )
    try:
        return DocType(doc_type.lower())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown document type '{doc_type}'.") from None
