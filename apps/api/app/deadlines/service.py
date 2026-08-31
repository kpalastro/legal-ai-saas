"""Deadline calculator (feature 5): jurisdiction rules, AU public holidays, arq reminder cron.

Rules are data, not code paths — adding a court = adding a row to DEADLINE_RULES.
All intervals are COURT BUSINESS days (weekends + gazetted holidays excluded),
as court rules specify. This is preparation assistance, not legal advice — always
surfaced next to the computed date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Fixed-date AU national/state public holidays (v1; move to a holiday lib if needed)
AU_HOLIDAYS_MONTH_DAY: dict[str, list[tuple[int, int]]] = {
    "all": [(1, 1)],
    "NSW": [(1, 26), (12, 25), (12, 26)],
    "VIC": [(1, 26), (12, 25), (12, 26)],
    "QLD": [(1, 26), (12, 25), (12, 26)],
}
ANZAC_DAY = (4, 25)


@dataclass(frozen=True)
class DeadlineRule:
    doc_trigger: str          # what document was filed/served
    respond_doc: str          # what the other side must file
    business_days: int        # interval
    jurisdiction: str         # "NSW Supreme Court", "Federal Court", ...


DEADLINE_RULES: tuple[DeadlineRule, ...] = (
    DeadlineRule("statement_of_claim", "defence", 28, "NSW Supreme Court"),
    DeadlineRule("statement_of_claim", "defence", 28, "Federal Court"),
    DeadlineRule("statement_of_claim", "defence", 28, "VIC Supreme Court"),
    DeadlineRule("court_correspondence", "court_correspondence", 14, "NSW Supreme Court"),
    DeadlineRule("defence", "reply", 14, "NSW Supreme Court"),
)


def is_business_day(d: date, jurisdiction: str) -> bool:
    if d.weekday() >= 5:  # Sat/Sun
        return False
    md = (d.month, d.day)
    if md in AU_HOLIDAYS_MONTH_DAY["all"] or md == ANZAC_DAY:
        return False
    state = jurisdiction.split()[-1] if jurisdiction and jurisdiction.split() else ""
    if md in AU_HOLIDAYS_MONTH_DAY.get(state, []):
        return False
    return True


def add_business_days(start: date, days: int, jurisdiction: str) -> date:
    d = start
    remaining = days
    while remaining > 0:
        d += timedelta(days=1)
        if is_business_day(d, jurisdiction):
            remaining -= 1
    return d


def compute_deadline(doc_type: str, jurisdiction: str, served_on: date | None = None) -> tuple[date, str] | None:
    """Return (due_date, respond_doc) or None if no rule matches."""
    if served_on is None:
        served_on = date.today()
    for rule in DEADLINE_RULES:
        if rule.doc_trigger == doc_type and rule.jurisdiction == jurisdiction:
            return add_business_days(served_on, rule.business_days, jurisdiction), rule.respond_doc
    return None


def disclaimer() -> str:
    return (
        "Deadline computed as preparation assistance only — verify against the "
        "current practice note and rules of the court before relying on it."
    )