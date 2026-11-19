"""Organisation/RBAC, consent, legal registry and metrics coverage."""

from __future__ import annotations

import time
import uuid

import httpx
import jwt
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.main import app


def _mint(sub: str, email: str) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "role": "authenticated",
            "aud": "",
            "email": email,
            "exp": int(time.time()) + 3600,
        },
        get_settings().supabase_jwt_secret,
        algorithm="HS256",
    )


async def _cleanup(sub: str) -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL session_replication_role = replica"))
            await conn.execute(
                text("DELETE FROM public.audit_log WHERE user_id = :u"), {"u": sub}
            )
            await conn.execute(text("SET LOCAL session_replication_role = DEFAULT"))
            await conn.execute(
                text("DELETE FROM public.cases WHERE user_id = :u"), {"u": sub}
            )
            await conn.execute(
                text("DELETE FROM public.users WHERE id = :u"), {"u": sub}
            )
            try:
                await conn.execute(
                    text("DELETE FROM auth.users WHERE id = :u"), {"u": sub}
                )
            except Exception:
                pass
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def api():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def user(api):
    sub = str(uuid.uuid4())
    email = f"org-a-{sub[:8]}@test.local"
    token = _mint(sub, email)
    yield {
        "id": sub,
        "email": email,
        "headers": {"Authorization": f"Bearer {token}"},
    }
    await _cleanup(sub)


@pytest_asyncio.fixture
async def second_user(api):
    sub = str(uuid.uuid4())
    email = f"org-b-{sub[:8]}@test.local"
    token = _mint(sub, email)
    # Mirror the user into public.users (normally happens on first case create).
    created = await api.post(
        "/cases",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "[TEST] second-user bootstrap",
            "jurisdiction": "NSW",
            "cause_of_action": "contract",
            "org_id": None,
        },
    )
    assert created.status_code == 201, created.text
    yield {
        "id": sub,
        "email": email,
        "headers": {"Authorization": f"Bearer {token}"},
    }
    await _cleanup(sub)


async def test_org_membership_rbac_and_case_sharing(api, user, second_user):
    created_case = await api.post(
        "/cases",
        headers=user["headers"],
        json={
            "title": "[TEST] shared matter",
            "jurisdiction": "NSW Supreme Court",
            "cause_of_action": "contract_breach",
            "description": "A contract was breached.",
            "parties": [{"name": "A. Plaintiff", "role": "plaintiff"}],
        },
    )
    assert created_case.status_code == 201
    case_id = created_case.json()["id"]

    org = await api.post(
        "/organisations", headers=user["headers"], json={"name": "Test Chambers"}
    )
    assert org.status_code == 201, org.text
    org_id = org.json()["id"]

    added = await api.post(
        f"/organisations/{org_id}/members",
        headers=user["headers"],
        json={"email": second_user["email"], "role": "lawyer"},
    )
    assert added.status_code == 201, added.text

    detail = await api.get(f"/organisations/{org_id}", headers=second_user["headers"])
    assert detail.status_code == 200
    assert len(detail.json()["members"]) == 2

    shared = await api.post(
        f"/cases/{case_id}/share",
        headers=user["headers"],
        json={"org_id": org_id},
    )
    assert shared.status_code == 200, shared.text

    # The lawyer sees the matter and can write to it.
    visible = await api.get(f"/cases/{case_id}", headers=second_user["headers"])
    assert visible.status_code == 200
    uploaded = await api.post(
        f"/cases/{case_id}/documents",
        headers=second_user["headers"],
        files={"file": ("note.txt", b"shared evidence", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text

    # But a lawyer cannot manage membership.
    denied = await api.post(
        f"/organisations/{org_id}/members",
        headers=second_user["headers"],
        json={"email": "nobody@example.com", "role": "viewer"},
    )
    assert denied.status_code == 403

    # Conflict check sees the shared matter's party and the register entry.
    check = await api.get(
        "/conflicts/check?name=A.%20Plaintiff", headers=user["headers"]
    )
    assert check.status_code == 200, check.text
    assert any(match["source"] == "case" for match in check.json()["matches"])
    entry = await api.post(
        "/conflicts",
        headers=user["headers"],
        json={
            "org_id": org_id,
            "party_name": "A. Plaintiff",
            "matter_ref": "shared matter",
        },
    )
    assert entry.status_code == 201, entry.text
    listed = await api.get(
        f"/organisations/{org_id}/conflicts", headers=user["headers"]
    )
    assert len(listed.json()) == 1

    # Demote to viewer: read still works, write does not.
    demoted = await api.patch(
        f"/organisations/{org_id}/members/{second_user['id']}",
        headers=user["headers"],
        json={"role": "viewer"},
    )
    assert demoted.status_code == 200
    still_visible = await api.get(f"/cases/{case_id}", headers=second_user["headers"])
    assert still_visible.status_code == 200
    blocked = await api.post(
        f"/cases/{case_id}/documents",
        headers=second_user["headers"],
        files={"file": ("blocked.txt", b"nope", "text/plain")},
    )
    assert blocked.status_code == 403

    removed = await api.delete(
        f"/organisations/{org_id}", headers=user["headers"]
    )
    assert removed.status_code == 200


async def test_consent_is_recorded(api, user):
    created = await api.post(
        "/cases",
        headers=user["headers"],
        json={
            "title": "[TEST] consent bootstrap",
            "jurisdiction": "NSW",
            "cause_of_action": "contract",
        },
    )
    assert created.status_code == 201
    response = await api.post(
        "/users/me/consent",
        headers=user["headers"],
        json={"consent_version": "2026-11-19"},
    )
    assert response.status_code == 201, response.text
    read = await api.get("/users/me/consent", headers=user["headers"])
    assert read.status_code == 200
    assert read.json()["consents"][0]["consent_version"] == "2026-11-19"


def test_legal_registry_endpoints():
    # Pure data endpoints are public; call the functions directly to avoid an
    # extra ASGI fixture for two static lookups.
    from app.legal_registry import elements_for, policy_for

    contract = elements_for("contract_breach")
    assert contract["known"] is True
    assert "Offer" in contract["elements"]
    assert elements_for("unknown_cause")["known"] is False

    nsw = policy_for("NSW Supreme Court")
    assert "SC Gen 23" in nsw["policy"]
    assert "affidavit" in nsw["prohibited_doc_types"]
    generic = policy_for("Some Tribunal")
    assert generic["policy"] == "No court-specific AI policy in the registry"


async def test_metrics_and_resources_endpoints(api):
    response = await api.get("/metrics")
    assert response.status_code == 200
    assert "lexsim_uptime_seconds" in response.text
    assert "# HELP lexsim_http_requests_total" in response.text

    resources = await api.get("/legal/resources")
    assert resources.status_code == 200
    names = {item["name"] for item in resources.json()["resources"]}
    assert {"Emergency", "Lifeline", "1800RESPECT"} <= names
