"""Log filter: scrub SSE `?token=` JWTs from any log line (security audit 31 Aug).

Uvicorn's access logs emit full request lines — without this filter, every SSE
debate stream would write the caller's HS256 JWT into stdout in plaintext as soon
as access logs (or a proxy with request logging) are enabled. Rewrites
`token=<jwt>` to `token=[REDACTED]` before the record reaches any handler.

Robust across all three uvicorn record shapes:
  1. msg with tuple args      -> getMessage() works, format + scrub + clear args
  2. msg with MAPPING args    -> getMessage() throws (tuple-vs-dict mismatch);
                                 scrub the raw msg instead, which is where the
                                 request line (and the JWT) actually lives
  3. pre-formatted msg, no args -> scrub in place
The scrub NEVER raises: a scrub failure must not break logging.
"""

from __future__ import annotations

import logging
import re

_TOKEN_RE = re.compile(r"([?&]token=)[^&\s]+")
REDACTED = r"\1[REDACTED]"


class TokenScrubFilter:
    """dictConfig-compatible filter ('()' factory in log_config.py)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Scrub the raw msg FIRST — record.msg is where the full request line
            # (and its query string) lives regardless of args shape; getMessage()
            # can throw when tuple args meet %-mapping placeholders.
            scrubbed = _TOKEN_RE.sub(REDACTED, record.msg)
            if scrubbed != record.msg:
                record.msg = scrubbed  # redacted in-place; args stay for the formatter
        except Exception:
            pass  # never break logging on a scrub failure
        return True