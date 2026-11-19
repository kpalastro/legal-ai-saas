"""Plan entitlements and usage checks.

The tier lives on `public.users.subscription_tier` and is written only by the
Stripe webhook. `NULL` means the free tier. Limits are deliberately simple and
enforced at the API edge (402 Payment Required) before work is queued or run.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import text


@dataclass(frozen=True)
class Limits:
    cases: int | None  # None = unlimited
    simulations_per_month: int | None


PLAN_LIMITS: dict[str, Limits] = {
    "free": Limits(cases=2, simulations_per_month=3),
    "individual_case_basic": Limits(cases=1, simulations_per_month=2),
    "individual_case_full": Limits(cases=3, simulations_per_month=10),
    "lawyer_monthly_10": Limits(cases=10, simulations_per_month=50),
    "lawyer_monthly_unlimited": Limits(cases=None, simulations_per_month=None),
}


def limits_for(tier: str | None) -> Limits:
    return PLAN_LIMITS.get(tier or "free", PLAN_LIMITS["free"])


def limits_dict(limits: Limits) -> dict:
    return {
        "cases": limits.cases,
        "simulations_per_month": limits.simulations_per_month,
    }


async def usage_for(db, user_id: str) -> dict:
    row = (
        await db.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM public.cases WHERE user_id = :u) AS cases,
                  (SELECT count(*) FROM public.simulations s
                     JOIN public.cases c ON c.id = s.case_id
                    WHERE c.user_id = :u
                      AND s.created_at >= date_trunc('month', now())) AS simulations_this_month
                """
            ),
            {"u": user_id},
        )
    ).mappings().first()
    return {
        "cases": int(row["cases"]) if row else 0,
        "simulations_this_month": int(row["simulations_this_month"]) if row else 0,
    }


async def _tier(db, user_id: str) -> str | None:
    return (
        await db.execute(
            text("SELECT subscription_tier FROM public.users WHERE id = :u"),
            {"u": user_id},
        )
    ).scalar_one_or_none()


async def enforce_case_limit(db, user_id: str) -> None:
    limits = limits_for(await _tier(db, user_id))
    if limits.cases is None:
        return
    usage = await usage_for(db, user_id)
    if usage["cases"] >= limits.cases:
        raise HTTPException(
            status_code=402,
            detail=(
                f"plan limit reached: {limits.cases} case(s). Upgrade to create"
                " another matter."
            ),
        )


async def enforce_simulation_limit(db, user_id: str) -> None:
    limits = limits_for(await _tier(db, user_id))
    if limits.simulations_per_month is None:
        return
    usage = await usage_for(db, user_id)
    if usage["simulations_this_month"] >= limits.simulations_per_month:
        raise HTTPException(
            status_code=402,
            detail=(
                f"plan limit reached: {limits.simulations_per_month} simulation(s)"
                " this month. Upgrade to run more."
            ),
        )
