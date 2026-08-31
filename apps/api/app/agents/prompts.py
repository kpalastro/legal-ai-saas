"""Debate agent role prompts — brief, persona-scoped, schema-pinning for JUDGE.

Nondeterminism contract (TEST_PLAN): tests never assert on prose, only structure.
JUDGE final verdict is instructed to emit {lower, point, upper}; the engine parses
leniently (raw-text fallback) and outcome_prediction always renders as a calibrated
range + "not legal advice" copy (ACL s18/s29) — never a bare point estimate.
"""

SYSTEM_PROMPTS: dict[str, str] = {
    "user_advocate": (
        "You are USER_ADVOCATE, counsel for the plaintiff in an Australian legal debate "
        "simulation. Argue the plaintiff's position forcefully but honestly. 2-4 sentences. "
        "No preamble, no thinking aloud."
    ),
    "opponent": (
        "You are OPPONENT, counsel for the defendant in an Australian legal debate "
        "simulation. Attack the plaintiff's weakest elements. 2-4 sentences. No preamble."
    ),
    "judge": (
        "You are JUDGE, a neutral adjudicator in an Australian legal debate simulation. "
        "For belief updates: assess both sides in 2-3 sentences, then state your current "
        "confidence the plaintiff wins as ONLY a JSON object "
        '{"lower": <int 0-100>, "point": <int 0-100>, "upper": <int 0-100>} '
        "with lower <= point <= upper. No other text."
    ),
}

# ACL s18/s29: predictions are never bare point estimates and never legal advice.
NOT_LEGAL_ADVICE = (
    "This is a simulated estimate, not legal advice. Actual outcomes depend on "
    "evidence, procedure and judicial discretion."
)


def verdict_from_text(text: str) -> dict:
    """Best-effort parse of the JUDGE's final verdict into the {lower,point,upper} schema.

    Never raises: unparseable output degrades to {"raw": text} so the range-rendering
    guard downstream can still show a compliant fallback.
    """
    import json
    import re

    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(0))
            if all(k in d for k in ("lower", "point", "upper")):
                return {
                    "lower": int(d["lower"]),
                    "point": int(d["point"]),
                    "upper": int(d["upper"]),
                    "note": "not legal advice",
                }
        except (ValueError, TypeError):
            pass
    return {"raw": text, "note": "not legal advice"}