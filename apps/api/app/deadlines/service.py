"""Deadline + limitation-period calculator (features 5 and 5b).

Rules are data, not code paths — adding a court or cause of action is a row.
Intervals are COURT BUSINESS days: weekends plus gazetted public holidays for the
relevant state are excluded. Easter is computed (not hard-coded) so the calendar
does not silently rot; fixed-date holidays are observed on the following Monday
when they fall on a weekend.

This is preparation assistance, not legal advice. Every response carries the
disclaimer, and limitation periods are deliberately conservative: only the
well-established NSW rules are encoded, and the user is told to verify.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

_STATES = {"NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"}


@dataclass(frozen=True)
class DeadlineRule:
    doc_trigger: str          # what document was filed/served
    respond_doc: str          # what the other side must file
    business_days: int        # interval
    jurisdiction: str         # "NSW Supreme Court", "Federal Court", ...


# The documented v1 rule set, widened to the equivalent 28-day defence rule for
# the other Supreme Courts and the FCFCOA. Every row is a claim about a court
# rule — verify against the current practice note before relying on it.
DEADLINE_RULES: tuple[DeadlineRule, ...] = (
    DeadlineRule("statement_of_claim", "defence", 28, "NSW Supreme Court"),
    DeadlineRule("statement_of_claim", "defence", 28, "Federal Court"),
    DeadlineRule("statement_of_claim", "defence", 28, "Federal Circuit and Family Court"),
    DeadlineRule("statement_of_claim", "defence", 28, "VIC Supreme Court"),
    DeadlineRule("statement_of_claim", "defence", 28, "QLD Supreme Court"),
    DeadlineRule("statement_of_claim", "defence", 28, "WA Supreme Court"),
    DeadlineRule("statement_of_claim", "defence", 28, "SA Supreme Court"),
    DeadlineRule("statement_of_claim", "defence", 28, "TAS Supreme Court"),
    DeadlineRule("statement_of_claim", "defence", 28, "ACT Supreme Court"),
    DeadlineRule("statement_of_claim", "defence", 28, "NT Supreme Court"),
    DeadlineRule("statement_of_claim", "defence", 28, "NSW Local Court"),
    DeadlineRule("court_correspondence", "court_correspondence", 14, "NSW Supreme Court"),
    DeadlineRule("defence", "reply", 14, "NSW Supreme Court"),
)


@dataclass(frozen=True)
class LimitationRule:
    cause_of_action: str
    jurisdiction: str
    years: int
    provision: str
    long_stop_years: int | None = None


# Conservative: only the settled NSW Limitation Act 1969 rules. Anything else
# returns None (the API says "no rule") rather than guessing.
LIMITATION_RULES: tuple[LimitationRule, ...] = (
    LimitationRule("contract", "NSW", 6, "Limitation Act 1969 (NSW) s 14"),
    LimitationRule("tort", "NSW", 6, "Limitation Act 1969 (NSW) s 14"),
    LimitationRule(
        "personal_injury", "NSW", 3, "Limitation Act 1969 (NSW) s 18A", long_stop_years=12
    ),
)


# ---------- public holidays ----------


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observed(day: date) -> date:
    if day.weekday() == 5:  # Saturday -> Monday
        return day + timedelta(days=2)
    if day.weekday() == 6:  # Sunday -> Monday
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th weekday (Mon=0) in a month; n=1 -> first."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _state_code(jurisdiction: str) -> str:
    """Find the state code anywhere in the court name.

    The old implementation took the LAST token, so "NSW Supreme Court" became
    "COURT" and no state public holidays were ever applied. Match known codes.
    """
    if not jurisdiction:
        return ""
    upper = jurisdiction.upper()
    for token in re.findall(r"[A-Z]{2,3}", upper):
        if token in _STATES:
            return token
    if "FEDERAL" in upper or "COMMONWEALTH" in upper or "CTH" in upper:
        return "CTH"
    return ""


def public_holidays(year: int, jurisdiction: str) -> set[date]:
    """National + state public holidays for the given calendar year."""
    easter = easter_sunday(year)
    days: set[date] = {
        _observed(date(year, 1, 1)),   # New Year's Day
        _observed(date(year, 1, 26)),  # Australia Day
        easter - timedelta(days=2),    # Good Friday
        easter + timedelta(days=1),    # Easter Monday
        _observed(date(year, 4, 25)),  # Anzac Day
        _observed(date(year, 12, 25)), # Christmas Day
    }
    # Boxing Day: if Christmas is observed on Monday, Boxing Day is Tuesday.
    boxing = date(year, 12, 26)
    if boxing.weekday() == 5:
        days.add(boxing + timedelta(days=2))
    elif boxing.weekday() == 6:
        days.add(boxing + timedelta(days=1))
    else:
        days.add(boxing)

    state = _state_code(jurisdiction)
    if state in {"NSW", "VIC", "SA", "TAS", "ACT", "NT"}:
        days.add(_nth_weekday(year, 6, 0, 2))  # King's Birthday (2nd Mon June)
    if state == "QLD":
        days.add(_nth_weekday(year, 10, 0, 1))  # King's Birthday (1st Mon Oct)
        days.add(_nth_weekday(year, 5, 0, 1))   # Labour Day
    if state in {"NSW", "ACT", "SA"}:
        days.add(_nth_weekday(year, 10, 0, 1))  # Labour Day
    if state == "VIC":
        days.add(_nth_weekday(year, 3, 0, 2))   # Labour Day
    if state == "WA":
        days.add(_nth_weekday(year, 3, 0, 1))   # Labour Day
        days.add(_nth_weekday(year, 6, 0, 1))   # WA Day
    if state == "TAS":
        days.add(_nth_weekday(year, 3, 0, 2))   # Eight Hours Day
    if state == "NT":
        days.add(_nth_weekday(year, 5, 0, 1))   # May Day
        days.add(_nth_weekday(year, 8, 0, 1))   # Picnic Day
    if state == "ACT":
        days.add(_nth_weekday(year, 3, 0, 2))   # Canberra Day
    return days


def is_business_day(d: date, jurisdiction: str, holidays: set[date] | None = None) -> bool:
    if d.weekday() >= 5:  # Sat/Sun
        return False
    if holidays is None:
        holidays = public_holidays(d.year, jurisdiction)
    return d not in holidays


def add_business_days(start: date, days: int, jurisdiction: str) -> date:
    d = start
    remaining = days
    holidays = public_holidays(start.year, jurisdiction) | public_holidays(
        (start + timedelta(days=400)).year, jurisdiction
    )
    while remaining > 0:
        d += timedelta(days=1)
        if is_business_day(d, jurisdiction, holidays):
            remaining -= 1
    return d


def compute_deadline(
    doc_type: str, jurisdiction: str, served_on: date | None = None
) -> tuple[date, str] | None:
    """Return (due_date, respond_doc) or None if no rule matches."""
    if served_on is None:
        served_on = date.today()
    for rule in DEADLINE_RULES:
        if rule.doc_trigger == doc_type and rule.jurisdiction == jurisdiction:
            return add_business_days(served_on, rule.business_days, jurisdiction), rule.respond_doc
    return None


def compute_limitation(
    cause_of_action: str, jurisdiction: str, accrual_on: date | None = None
) -> dict | None:
    """Return the limitation-period record for a supported cause, or None."""
    if accrual_on is None:
        accrual_on = date.today()
    state = _state_code(jurisdiction)
    cause = cause_of_action.strip().lower().replace(" ", "_")
    for rule in LIMITATION_RULES:
        if rule.cause_of_action == cause and rule.jurisdiction == state:
            due = date(accrual_on.year + rule.years, accrual_on.month, accrual_on.day)
            long_stop = (
                date(accrual_on.year + rule.long_stop_years, accrual_on.month, accrual_on.day)
                if rule.long_stop_years
                else None
            )
            return {
                "due_date": due.isoformat(),
                "years": rule.years,
                "provision": rule.provision,
                "long_stop_date": long_stop.isoformat() if long_stop else None,
                "disclaimer": disclaimer(
                    "Limitation periods are fact-specific and may be extended, suspended "
                    "or expired earlier. This is preparation assistance only."
                ),
            }
    return None


def disclaimer(extra: str = "") -> str:
    base = (
        "Deadline computed as preparation assistance only — verify against the "
        "current practice note and rules of the court before relying on it."
    )
    return f"{base} {extra}".strip()
