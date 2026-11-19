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

# Bump whenever a system prompt changes; written to audit_log.prompt_version so
# a historical output can be tied to the exact prompt that produced it.
PROMPT_VERSION = "2026-11-19"

# ACL s18/s29: predictions are never bare point estimates and never legal advice.
NOT_LEGAL_ADVICE = (
    "This is a simulated estimate, not legal advice. Actual outcomes depend on "
    "evidence, procedure and judicial discretion."
)
METHODOLOGY_NOTE = (
    "Model-generated scenario estimate from a 9-turn adversarial simulation. "
    "It is not a statistical prediction, has not been calibrated against decided "
    "cases, and must not be presented as a probability of success."
)

# Post-debate analysis. This is deliberately NOT a tenth protocol turn: G6 fixes
# the debate at nine turns; analysis is a separate, audited request.
ANALYSIS_SYSTEM = (
    "You are a case-strategy analyst in an Australian legal preparation tool. "
    "Read the case brief and the nine-turn simulation transcript. Identify the "
    "concrete weaknesses a court or opponent would exploit: missing elements, "
    "evidence gaps, credibility problems, procedural risks. Do not invent facts "
    "or authorities. Respond with ONLY a JSON object: "
    '{"summary": "<2-4 sentences>", '
    '"weaknesses": [{"issue": "<short label>", '
    '"side": "plaintiff"|"defendant", '
    '"severity": "high"|"medium"|"low", '
    '"why": "<why it matters>", '
    '"evidence_gap": "<what is missing, or empty>", '
    '"next_step": "<a concrete preparation step>"}], '
    '"claims": [{"claim": "<a factual or legal assertion made in the debate>", '
    '"support": "supported"|"unsupported"|"uncertain", '
    '"source": "<what supports it, or empty>"}], '
    '"elements": [{"element": "<element of the cause of action>", '
    '"status": "addressed"|"missing"|"unclear", '
    '"note": "<what the transcript does or does not establish>"}], '
    '"settlement": {"range": "<indicative negotiation range, or empty if not meaningful>", '
    '"factors": ["<factor that moves the range>"], '
    '"cost_risks": ["<procedural or cost risk>"]}}'
)

ANALYSIS_INSTRUCTION = (
    "Analyse the transcript below and return the JSON object described. "
    "Be specific to this case; no generic advice. 3-8 weaknesses maximum."
)


def parse_weakness_report(text: str) -> dict:
    """Best-effort, bounded parse of the analysis JSON. Never raises."""
    import json
    import re

    allowed_severity = {"high", "medium", "low"}
    allowed_side = {"plaintiff", "defendant"}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            summary = str(data.get("summary", ""))[:4_000]
            raw_items = data.get("weaknesses")
            weaknesses: list[dict] = []
            if isinstance(raw_items, list):
                for item in raw_items[:12]:
                    if not isinstance(item, dict):
                        continue
                    severity = str(item.get("severity", "medium")).lower()
                    side = str(item.get("side", "plaintiff")).lower()
                    issue = str(item.get("issue", "")).strip()[:300]
                    if not issue:
                        continue
                    weaknesses.append(
                        {
                            "issue": issue,
                            "side": side if side in allowed_side else "plaintiff",
                            "severity": severity
                            if severity in allowed_severity
                            else "medium",
                            "why": str(item.get("why", ""))[:1_500],
                            "evidence_gap": str(item.get("evidence_gap", ""))[:1_500],
                            "next_step": str(item.get("next_step", ""))[:1_500],
                        }
                    )
            claims: list[dict] = []
            raw_claims = data.get("claims")
            if isinstance(raw_claims, list):
                for item in raw_claims[:20]:
                    if not isinstance(item, dict):
                        continue
                    claim = str(item.get("claim", "")).strip()[:500]
                    if not claim:
                        continue
                    support = str(item.get("support", "uncertain")).lower()
                    claims.append(
                        {
                            "claim": claim,
                            "support": support
                            if support in {"supported", "unsupported", "uncertain"}
                            else "uncertain",
                            "source": str(item.get("source", ""))[:500],
                        }
                    )

            elements: list[dict] = []
            raw_elements = data.get("elements")
            if isinstance(raw_elements, list):
                for item in raw_elements[:20]:
                    if not isinstance(item, dict):
                        continue
                    element = str(item.get("element", "")).strip()[:300]
                    if not element:
                        continue
                    status = str(item.get("status", "unclear")).lower()
                    elements.append(
                        {
                            "element": element,
                            "status": status
                            if status in {"addressed", "missing", "unclear"}
                            else "unclear",
                            "note": str(item.get("note", ""))[:1_000],
                        }
                    )

            settlement: dict = {}
            raw_settlement = data.get("settlement")
            if isinstance(raw_settlement, dict):
                factors = raw_settlement.get("factors")
                costs = raw_settlement.get("cost_risks")
                settlement = {
                    "range": str(raw_settlement.get("range", ""))[:300],
                    "factors": [
                        str(item)[:300]
                        for item in (factors if isinstance(factors, list) else [])[:10]
                    ],
                    "cost_risks": [
                        str(item)[:300]
                        for item in (costs if isinstance(costs, list) else [])[:10]
                    ],
                }

            return {
                "summary": summary,
                "weaknesses": weaknesses,
                "claims": claims,
                "elements": elements,
                "settlement": settlement,
                "note": "not legal advice",
                "methodology_note": (
                    "Model-generated preparation analysis, not a legal opinion. "
                    "Verify every factual and legal proposition before relying on it."
                ),
            }
    return {
        "summary": text[:2_000],
        "weaknesses": [],
        "claims": [],
        "elements": [],
        "settlement": {},
        "parse_error": True,
        "note": "not legal advice",
        "methodology_note": "The analysis response was not valid JSON; raw text retained.",
    }


def verdict_from_text(text: str) -> dict:
    """Parse the JUDGE's final verdict into a validated {lower,point,upper} range.

    Never raises. A malformed, out-of-range, or misordered object degrades to
    {"raw": text} so the downstream range guard still shows a compliant fallback.
    Validation matters: the previous version accepted any integers, so a model
    could return lower > upper or 0-1000 and the API would pass it through.
    """
    import json
    import re

    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(0))
            if all(k in d for k in ("lower", "point", "upper")):
                lower, point, upper = (int(d[k]) for k in ("lower", "point", "upper"))
                if 0 <= lower <= point <= upper <= 100:
                    return {
                        "lower": lower,
                        "point": point,
                        "upper": upper,
                        "note": "not legal advice",
                        "methodology_note": METHODOLOGY_NOTE,
                    }
        except (ValueError, TypeError):
            pass
    return {"raw": text, "note": "not legal advice", "methodology_note": METHODOLOGY_NOTE}