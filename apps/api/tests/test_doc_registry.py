"""G3: doc-registry hard block (SC Gen 23 para 10/20) + registry shape."""

import pytest
from fastapi import HTTPException

from app.documents.registry import PROHIBITED_DOC_TYPES, DocType, require_allowed_doc_type


@pytest.mark.parametrize("bad", ["affidavit", "witness_statement", "expert_report", "Affidavit"])
def test_prohibited_types_rejected(bad: str) -> None:
    with pytest.raises(HTTPException) as exc:
        require_allowed_doc_type(bad)
    assert exc.value.status_code == 422


def test_prohibited_set_covers_sc_gen_23() -> None:
    assert {"affidavit", "witness_statement", "expert_report"} <= PROHIBITED_DOC_TYPES


def test_allowed_types_pass() -> None:
    assert require_allowed_doc_type("statement_of_claim") == DocType.STATEMENT_OF_CLAIM


def test_unknown_type_rejected() -> None:
    with pytest.raises(HTTPException):
        require_allowed_doc_type("nonsense")
