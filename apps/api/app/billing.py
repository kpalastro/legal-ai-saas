"""Stripe billing: real Checkout Session creation + webhook signature verification.

No fake checkout URLs. If Stripe is not configured the API returns 503 rather
than pretending a payment happened. The webhook is the only place entitlements
are granted, and it verifies the `Stripe-Signature` HMAC before trusting a byte.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import httpx

from app.config import get_settings

STRIPE_API = "https://api.stripe.com/v1"
WEBHOOK_TOLERANCE_SECONDS = 300


@dataclass(frozen=True)
class Plan:
    id: str
    label: str
    amount_cents: int
    currency: str = "aud"
    interval: str | None = None  # None = one-off, "month" = subscription


PLANS: dict[str, Plan] = {
    "individual_case_basic": Plan("individual_case_basic", "LexSim case — basic", 4900),
    "individual_case_full": Plan("individual_case_full", "LexSim case — full", 14900),
    "lawyer_monthly_10": Plan("lawyer_monthly_10", "LexSim lawyer — 10 cases/mo", 9900, interval="month"),
    "lawyer_monthly_unlimited": Plan(
        "lawyer_monthly_unlimited", "LexSim lawyer — unlimited", 29900, interval="month"
    ),
}


class BillingUnavailable(RuntimeError):
    """Stripe is not configured — the caller should return 503."""


class WebhookError(ValueError):
    """Missing/invalid Stripe signature."""


async def create_checkout_session(
    *, user_id: str, email: str | None, plan_id: str
) -> dict:
    settings = get_settings()
    plan = PLANS.get(plan_id)
    if plan is None:
        raise KeyError(plan_id)
    if not settings.stripe_secret_key:
        raise BillingUnavailable("Stripe is not configured (STRIPE_SECRET_KEY)")

    data: dict[str, str] = {
        "mode": "subscription" if plan.interval else "payment",
        "success_url": settings.checkout_success_url,
        "cancel_url": settings.checkout_cancel_url,
        "client_reference_id": user_id,
        "metadata[plan]": plan.id,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": plan.currency,
        "line_items[0][price_data][product_data][name]": plan.label,
        "line_items[0][price_data][unit_amount]": str(plan.amount_cents),
    }
    if plan.interval:
        data["line_items[0][price_data][recurring][interval]"] = plan.interval
    if email:
        data["customer_email"] = email

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
        response = await client.post(
            f"{STRIPE_API}/checkout/sessions",
            data=data,
            auth=(settings.stripe_secret_key, ""),
        )
        response.raise_for_status()
        body = response.json()
    return {
        "id": body.get("id"),
        "url": body.get("url"),
        "mode": data["mode"],
        "plan": plan.id,
        "amount_cents": plan.amount_cents,
        "currency": plan.currency,
    }


def verify_webhook(payload: bytes, signature_header: str | None) -> dict:
    """Verify and parse a Stripe webhook.

    Stripe sends `t=<unix>,v1=<hex>[,v1=<hex>]`. The signed payload is
    `<t>.<raw body>`. Reject stale timestamps to blunt replay.
    """
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise BillingUnavailable("Stripe webhook secret is not configured")
    if not signature_header:
        raise WebhookError("missing Stripe-Signature header")

    parts: dict[str, list[str]] = {}
    for item in signature_header.split(","):
        key, _, value = item.partition("=")
        parts.setdefault(key.strip(), []).append(value.strip())
    try:
        timestamp = int(parts["t"][0])
    except (KeyError, ValueError, IndexError):
        raise WebhookError("malformed Stripe-Signature header") from None
    if abs(time.time() - timestamp) > WEBHOOK_TOLERANCE_SECONDS:
        raise WebhookError("stale webhook signature")

    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(
        settings.stripe_webhook_secret.encode(), signed, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in parts.get("v1", [])):
        raise WebhookError("invalid webhook signature")

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        raise WebhookError("invalid webhook JSON") from None


def entitlement_from_event(event: dict) -> tuple[str, str] | None:
    """Return (user_id, plan_id) for a completed checkout, else None."""
    if event.get("type") != "checkout.session.completed":
        return None
    session = event.get("data", {}).get("object", {})
    user_id = session.get("client_reference_id")
    plan_id = (session.get("metadata") or {}).get("plan")
    if not user_id or plan_id not in PLANS:
        return None
    return str(user_id), str(plan_id)
