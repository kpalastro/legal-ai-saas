"""Small, deliberately conservative legal-content registry.

Two things the model should not have to invent:
  * the elements of the common causes of action, as a preparation checklist;
  * which court AI policy applies to a matter.

This is a pointer, not legal advice. Every entry carries a verify note; the
court registry must be reviewed against the current practice note before real
filings. Extend by adding data, not code paths.
"""

from __future__ import annotations

DISCLAIMER = (
    "Preparation assistance only. This registry is not legal advice; verify the "
    "current practice note, rules and elements before relying on it."
)

CAUSE_ALIASES = {
    "contract_breach": "contract",
    "breach_of_contract": "contract",
    "contract": "contract",
    "negligence": "negligence",
    "personal_injury": "negligence",
    "defamation": "defamation",
    "family_law_property": "family_law_property",
    "property_settlement": "family_law_property",
    "employment": "employment",
    "unfair_dismissal": "employment",
    "tenancy": "tenancy",
}

CAUSE_ELEMENTS: dict[str, list[str]] = {
    "contract": [
        "Offer",
        "Acceptance",
        "Consideration",
        "Intention to create legal relations",
        "Breach",
        "Loss or damage caused by the breach",
    ],
    "negligence": [
        "Duty of care",
        "Breach of the standard of care",
        "Causation (factual and scope of liability)",
        "Damage",
    ],
    "defamation": [
        "Publication to a third party",
        "Identification of the plaintiff",
        "Defamatory meaning",
        "Serious harm (where required)",
    ],
    "family_law_property": [
        "Identify the asset pool and liabilities",
        "Contributions (financial and non-financial)",
        "Future needs and circumstances",
        "A just and equitable alteration of property interests",
    ],
    "employment": [
        "Basis of the obligation (contract/statute/award)",
        "Breach or adverse action",
        "Loss and remedy",
    ],
    "tenancy": [
        "Existence and terms of the tenancy",
        "Breach or termination ground",
        "Notice and procedural requirements",
        "Loss, bond or possession remedy",
    ],
}


COURT_POLICIES: list[dict] = [
    {
        "court": "NSW Supreme Court",
        "policy": "Practice Note SC Gen 23 (Use of Generative AI)",
        "ai_disclosure_required": True,
        "citation_verification_required": True,
        "human_review_required": True,
        "prohibited_doc_types": [
            "affidavit",
            "witness_statement",
            "expert_report",
            "evidentiary_material",
        ],
        "notes": (
            "This product blocks the prohibited document types and requires citation "
            "verification plus user attestation before export."
        ),
        "verified_on": "2026-08-31",
    },
    {
        "court": "Federal Court",
        "policy": "Generative AI Practice Note (GPN-AI)",
        "ai_disclosure_required": True,
        "citation_verification_required": True,
        "human_review_required": True,
        "prohibited_doc_types": [],
        "notes": (
            "Disclose AI assistance, verify every citation, and have a human review "
            "the generated content. Verify the current GPN-AI version."
        ),
        "verified_on": None,
    },
    {
        "court": "Federal Circuit and Family Court",
        "policy": "FCFCOA AI guidance",
        "ai_disclosure_required": True,
        "citation_verification_required": True,
        "human_review_required": True,
        "prohibited_doc_types": [],
        "notes": "Verify the current FCFCOA guidance before filing.",
        "verified_on": None,
    },
]

GENERIC_POLICY = {
    "court": "Unspecified",
    "policy": "No court-specific AI policy in the registry",
    "ai_disclosure_required": True,
    "citation_verification_required": True,
    "human_review_required": True,
    "prohibited_doc_types": [],
    "notes": (
        "Do not assume this court permits AI-assisted documents. Check the court's "
        "current practice note/guidance first."
    ),
    "verified_on": None,
}


def _normalise_cause(cause: str) -> str:
    key = (cause or "").strip().lower().replace(" ", "_")
    return CAUSE_ALIASES.get(key, key)


def elements_for(cause: str) -> dict:
    key = _normalise_cause(cause)
    elements = CAUSE_ELEMENTS.get(key)
    return {
        "cause": key,
        "known": elements is not None,
        "elements": elements or [],
        "disclaimer": DISCLAIMER,
    }


def policy_for(court: str) -> dict:
    wanted = (court or "").strip().lower()
    for policy in COURT_POLICIES:
        if wanted and policy["court"].lower() in wanted:
            return {**policy, "disclaimer": DISCLAIMER}
    return {**GENERIC_POLICY, "disclaimer": DISCLAIMER}
