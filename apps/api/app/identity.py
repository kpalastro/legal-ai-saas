"""Optional GoTrue admin deletion for account erasure.

De-identifying app data does not remove the auth identity. If the GoTrue admin
API is configured (service role key), delete the identity too; otherwise the
erasure response tells the caller it must be done in the auth console.
"""

from __future__ import annotations

import httpx

from app.config import get_settings


async def delete_identity(user_id: str) -> bool:
    settings = get_settings()
    if not settings.gotrue_admin_url or not settings.gotrue_service_role_key:
        return False
    url = f"{settings.gotrue_admin_url.rstrip('/')}/admin/users/{user_id}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            response = await client.delete(
                url,
                headers={
                    "Authorization": f"Bearer {settings.gotrue_service_role_key}",
                    "apikey": settings.gotrue_service_role_key,
                },
            )
        return response.status_code in (200, 204)
    except httpx.HTTPError:
        return False
