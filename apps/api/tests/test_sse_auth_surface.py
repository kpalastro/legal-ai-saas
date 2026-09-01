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
    planned one-release notice."""
    import sys

    sys.path.insert(0, str(DB_PY.parents[1]))
    from fastapi.routing import APIRoute

    from app.main import app

    def iter_api_routes():
        stack = list(app.router.routes)
        while stack:
            r = stack.pop()
            if isinstance(r, APIRoute):
                yield r
            sub = getattr(r, "routes", None)

            if sub:  # _IncludedRouter / sub-routers
                stack.extend(sub)

    sse = [r for r in iter_api_routes() if r.path.endswith("/simulate")]
    assert sse, "SSE route vanished from the router — this test must be updated"
    sse = sse[0]
    token_param = next(
        (p for p in sse.dependant.query_params if p.name == "token"), None
    )
    assert token_param is not None, (
        "?token= legacy path removed — update this test + PENDING.md (removal is "
        "the planned Phase-2 close, not an accident)"
    )
    assert token_param.default is None, "token query param must stay optional"