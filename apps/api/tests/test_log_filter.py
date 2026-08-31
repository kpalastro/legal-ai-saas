"""Security audit 31 Aug — TokenScrubFilter must redact JWTs in ALL uvicorn shapes.

Covers the regression deploy found in c08c3c7: the filter only scrubbed record.msg,
but uvicorn's AccessFormatter puts the request line in record.args (a 5-tuple) and
builds it at format time — so '?token=…' never appeared in msg and the JWT printed
raw. Fixed filter scrubs BOTH msg and every str element of args.
"""

from __future__ import annotations

import logging

import pytest

from app.log_filter import TokenScrubFilter

FILTER = TokenScrubFilter()


def _record(shape: str) -> logging.LogRecord:
    if shape == "tuple-template":
        # Actual uvicorn access emission: %-template msg + 5-tuple args.
        return logging.LogRecord(
            "uvicorn.access", 20, "x", 1,
            '%(client_addr)s - "%(request_line)s" %(status_code)s',
            ("1.2.3.4", "GET /cases/abc/simulate?token=JWT123 HTTP/1.1", 200),
            None,
        )
    if shape == "plain":
        return logging.LogRecord(
            "uvicorn.access", 20, "x", 1,
            "GET /cases/abc/simulate?token=JWT123 200", None, None,
        )
    return logging.LogRecord(
        "uvicorn.access", 20, "x", 1, "GET /healthz 200", None, None,
    )


@pytest.mark.parametrize("shape", ["tuple-template", "plain", "clean"])
def test_token_scrubbed(shape: str) -> None:
    r = _record(shape)
    assert FILTER.filter(r) is True
    blob = repr((r.msg, r.args))
    assert "JWT123" not in blob
    if shape != "clean":
        assert "[REDACTED]" in blob


def test_tuple_args_preserved_after_scrub() -> None:
    """AccessFormatter unpacks 5 values — scrub must not change arity."""
    r = _record("tuple-template")
    FILTER.filter(r)
    assert isinstance(r.args, tuple) and len(r.args) == 3  # (addr, request_line, status)
    assert r.args[1] == "GET /cases/abc/simulate?token=[REDACTED] HTTP/1.1"


def test_scrub_never_raises() -> None:
    r = logging.LogRecord("uvicorn.access", 20, "x", 1,
                          "%(client_addr)s", (None,), None)
    assert FILTER.filter(r) is True