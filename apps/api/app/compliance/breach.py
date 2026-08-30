"""C4 — OAIC breach-notification workflow stub (30-day assessment window).

Wired to Sentry alerting in production. Real notifier job lands when incident
response runbook is signed off; this provides the compliant entry points now.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

ASSESSMENT_WINDOW_DAYS = 30  # OAIC Notifiable Data Breaches scheme


@dataclass
class BreachIncident:
    detected_at: datetime
    description: str
    affected_users: list[str]
    assessment_due: datetime  # detected_at + 30 days
    notified_oaic: bool = False
    notified_users: bool = False


def open_incident(description: str, affected_users: list[str]) -> BreachIncident:
    now = datetime.now(UTC)
    return BreachIncident(
        detected_at=now,
        description=description,
        affected_users=affected_users,
        assessment_due=now + timedelta(days=ASSESSMENT_WINDOW_DAYS),
    )


# TODO(C4): notifier job (arq) — 30-day assessment reminder, OAIC + user notification
# templates, Sentry alert binding.
