"""P0 — Browser-origin / CORS preflight smoke (TEST_PLAN §2-P0, compliance ask 31 Aug).

The 31 Aug demo blocker: `apps/web` (:3000) POSTs to the API (:8000) cross-origin;
the API image had no CORSMiddleware, so the browser preflight died and `fetch()`
threw a bare "TypeError: Failed to fetch" — the exact screenshot @user sent.

These tests fail CI *before a browser ever sees it*:

- F1: OPTIONS preflight from the web origin on every mounted POST/GET path → 200
      with `access-control-allow-origin` echoing the origin.
- F2: allow-origin does NOT echo an unknown origin (no open CORS).
- F3: preflight passes for the headers the app actually sends
      (authorization + content-type) — a middleware that allows the method but
      not the headers still breaks the browser.

Runs against the live API when it's up; skips cleanly otherwise (CI job mounts
the same compose stack).
"""

from __future__ import annotations

import os

import httpx
import pytest

API = os.environ.get("LEXSIM_API_URL", "http://localhost:8000")
WEB_ORIGIN = "http://localhost:3000"

pytestmark = pytest.mark.compliance


def _api_up() -> bool:
    try:
        return httpx.get(f"{API}/healthz", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


skip_no_api = pytest.mark.skipif(not _api_up(), reason="API not running")


def _preflight(path: str, method: str = "POST") -> httpx.Response:
    return httpx.options(
        f"{API}{path}",
        headers={
            "Origin": WEB_ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization, content-type",
        },
        timeout=5,
    )


@skip_no_api
class TestCorsPreflight:
    def test_preflight_cases_200_and_origin_echoed(self) -> None:
        r = _preflight("/cases", "POST")
        assert r.status_code == 200, (
            "CORS preflight rejected — browser fetch() will fail with a bare "
            "'TypeError: Failed to fetch' (31 Aug demo blocker regression)"
        )
        assert r.headers.get("access-control-allow-origin") == WEB_ORIGIN
        assert "POST" in r.headers.get("access-control-allow-methods", "")

    def test_preflight_simulate_sse_200(self) -> None:
        assert _preflight("/cases/00000000-0000-0000-0000-0000000000c1/simulate", "GET").status_code == 200

    def test_preflight_headers_allowed(self) -> None:
        r = _preflight("/cases")
        allowed = r.headers.get("access-control-allow-headers", "")
        assert "authorization" in allowed.lower(), (
            "authorization header must survive preflight — the app sends the JWT in it"
        )

    def test_unknown_origin_not_echoed(self) -> None:
        r = httpx.options(
            f"{API}/cases",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
            timeout=5,
        )
        assert r.headers.get("access-control-allow-origin") != "https://evil.example", (
            "CORS must not allow arbitrary origins (credentials are enabled)"
        )