"""Legal-content registry endpoints (elements + court AI policies)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.legal_registry import COURT_POLICIES, DISCLAIMER, elements_for, policy_for
from app.resources import DISCLAIMER as RESOURCE_DISCLAIMER
from app.resources import RESOURCES

router = APIRouter(prefix="/legal", tags=["legal"])


@router.get("/elements")
async def elements(cause: str = Query(min_length=1, max_length=120)) -> dict:
    return elements_for(cause)


@router.get("/resources")
async def resources() -> dict:
    return {"resources": RESOURCES, "disclaimer": RESOURCE_DISCLAIMER}


@router.get("/court-policies")
async def court_policies(court: str | None = None) -> dict:
    if court:
        return policy_for(court)
    return {
        "policies": [
            {**policy, "disclaimer": DISCLAIMER} for policy in COURT_POLICIES
        ],
        "generic": policy_for(""),
        "disclaimer": DISCLAIMER,
    }
