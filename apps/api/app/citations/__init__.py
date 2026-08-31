"""Citation extraction/verification (feature 4). See service.py for the model."""

from app.citations.service import (  # noqa: F401
    CitationFinding,
    CitationStatus,
    CITATION_SOURCE_DENYLIST,
    extract_citations,
    verify_citations,
)