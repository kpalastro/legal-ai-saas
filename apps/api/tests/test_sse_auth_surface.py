"""SSE credential surface: header-only, no query tokens (Phase-2 item ③).

The one-release `?token=` compatibility window is over. These tests keep the
removal from silently regressing:
  1. the FE sends the JWT via Authorization header (fetch + ReadableStream);
  2. `get_db` no longer accepts a query token;
  3. the OpenAPI wire contract exposes Authorization and no `token` param.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DB_PY = Path(__file__).resolve().parents[1] / "app" / "db.py"
PAGE_TSX = Path(__file__).resolve().parents[2] / "web" / "app" / "page.tsx"


def test_sse_primary_path_is_header_auth() -> None:
    src = PAGE_TSX.read_text()
    assert "EventSource(" not in src.replace("as unknown as EventSource", ""), (
        "EventSource (query-param SSE) has returned to the frontend — the header-safe "
        "fetch+ReadableStream path is the only approved client"
    )
    assert "Authorization: `Bearer ${token}`" in src, "SSE fetch must carry the header"


def test_query_token_fallback_is_removed() -> None:
    src = DB_PY.read_text()
    # The docstring may explain the removal; the executable surface may not
    # accept or read a query token.
    assert "token: str | None" not in src, "the query-token parameter must not return"
    assert "elif token:" not in src, "query-token fallback branch must not return"
    assert "request.query_params" not in src


@pytest.mark.compliance
def test_openapi_has_no_query_token() -> None:
    """`token` must be gone from the OpenAPI contract; the header must remain."""
    from app.main import app

    spec = app.openapi()
    sse = spec["paths"]["/cases/{case_id}/simulate"]["get"]
    params = {p["name"]: p for p in sse["parameters"]}
    assert "token" not in params, "query token reappeared on the SSE route"
    assert "Authorization" in params and params["Authorization"]["in"] == "header"
