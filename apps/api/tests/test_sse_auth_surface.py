"""Phase-2 item ③ acceptance: header-safe SSE + documented-legacy ?token=.

Three compliance-marked tests per the security plan (SECURITY_PHASE2_PLAN.md):
  1. The FE sends the JWT via Authorization header (fetch+ReadableStream, no EventSource).
  2. ?token= remains accepted but is documented as legacy/deprecated in db.py.
  3. The OpenAPI surface still exposes `token` as an OPTIONAL query param on the
     SSE route — hard-requiring it would break header clients; removing it breaks
     legacy clients before the planned one-release notice.
Acceptance criterion (plan): SSE works with no credential in any URL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DB_PY = Path(__file__).resolve().parents[1] / "app" / "db.py"
PAGE_TSX = Path(__file__).resolve().parents[2] / "web" / "app" / "page.tsx"


def test_sse_primary_path_is_header_auth() -> None:
    """The web client must send the JWT via Authorization header — no ?token= in code."""
    src = PAGE_TSX.read_text()
    assert "EventSource(" not in src.replace("as unknown as EventSource", ""), (
        "EventSource (query-param SSE) has returned to the frontend — the header-safe "
        "fetch+ReadableStream path is the only approved client (Phase-2 item 3)"
    )
    assert "Authorization: `Bearer ${token}`" in src, "SSE fetch must carry the header"


def test_query_token_is_documented_legacy() -> None:
    """The API still ACCEPTS ?token= (one-release-window legacy) but the code must
    say so — the docstring carries the deprecation contract @security specified."""
    src = DB_PY.read_text()
    assert "?token= fallback" in src
    assert "LEGACY" in src, (
        "db.py must mark the query-token accept path as legacy so its removal is "
        "tracked, not silent"
    )


@pytest.mark.compliance
def test_openapi_token_param_is_query_optional_not_required() -> None:
    """`token` must remain OPTIONAL on the SSE route — hard-requiring it would
    break header-auth clients; removing it breaks legacy clients without the
    planned one-release notice. Asserted against the OpenAPI schema (the wire
    contract) because FastAPI 0.11x builds query params at include-time, so the
    bare APIRoute.dependant is empty (verified 31 Aug)."""
    from app.main import app

    spec = app.openapi()
    sse = spec["paths"]["/cases/{case_id}/simulate"]["get"]
    params = {p["name"]: p for p in sse["parameters"]}
    assert "token" in params, "?token= legacy path removed — update this test + PENDING.md (removal is the planned Phase-2 close, not an accident)"
    assert params["token"]["in"] == "query"
    assert params["token"]["required"] is False
    # header auth remains available on the same route
    assert "Authorization" in params and params["Authorization"]["in"] == "header"
