"""Organisation/team API: create orgs, manage members, share matters, consent."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.organisations import (
    add_member,
    create_org,
    get_consents,
    get_org,
    list_orgs,
    record_consent,
    remove_member,
    share_case,
    unshare_case,
    update_member,
)

router = APIRouter(tags=["organisations"])


async def _caller_sub(db: AsyncSession) -> str:
    sub = (
        await db.execute(
            text("SELECT current_setting('request.jwt.claims', true)::jsonb ->> 'sub'")
        )
    ).scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=401, detail="no verified identity on the session")
    return str(sub)


class OrgBody(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class MemberBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = Field(default="lawyer", max_length=20)


class MemberRoleBody(BaseModel):
    role: str = Field(min_length=2, max_length=20)


class ShareBody(BaseModel):
    org_id: str


class ConsentBody(BaseModel):
    consent_version: str = Field(min_length=1, max_length=40)


@router.post("/organisations", status_code=201)
async def create(body: OrgBody, db: AsyncSession = Depends(get_db)) -> dict:
    user_id = await _caller_sub(db)
    org = await create_org(db, user_id, body.name)
    await db.commit()
    return org


@router.get("/organisations")
async def list_mine(db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await list_orgs(db, await _caller_sub(db))


@router.get("/organisations/{org_id}")
async def detail(org_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    return await get_org(db, org_id, await _caller_sub(db))


@router.delete("/organisations/{org_id}")
async def remove_org(org_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    user_id = await _caller_sub(db)
    row = (
        await db.execute(
            text(
                "DELETE FROM public.organisations"
                " WHERE id = :o AND owner_id = :u RETURNING id"
            ),
            {"o": org_id, "u": user_id},
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="organisation not found")
    await db.commit()
    return {"id": str(row), "deleted": True}


@router.post("/organisations/{org_id}/members", status_code=201)
async def add(
    org_id: str, body: MemberBody, db: AsyncSession = Depends(get_db)
) -> dict:
    result = await add_member(
        db, org_id, await _caller_sub(db), body.email.lower(), body.role
    )
    await db.commit()
    return result


@router.patch("/organisations/{org_id}/members/{user_id}")
async def update(
    org_id: str, user_id: str, body: MemberRoleBody, db: AsyncSession = Depends(get_db)
) -> dict:
    result = await update_member(
        db, org_id, await _caller_sub(db), user_id, body.role
    )
    await db.commit()
    return result


@router.delete("/organisations/{org_id}/members/{user_id}")
async def remove(
    org_id: str, user_id: str, db: AsyncSession = Depends(get_db)
) -> dict:
    result = await remove_member(db, org_id, await _caller_sub(db), user_id)
    await db.commit()
    return result


@router.post("/cases/{case_id}/share")
async def share(
    case_id: str, body: ShareBody, db: AsyncSession = Depends(get_db)
) -> dict:
    result = await share_case(db, case_id, await _caller_sub(db), body.org_id)
    await db.commit()
    return result


@router.delete("/cases/{case_id}/share")
async def unshare(case_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await unshare_case(db, case_id, await _caller_sub(db))
    await db.commit()
    return result


@router.post("/users/me/consent", status_code=201)
async def consent(body: ConsentBody, db: AsyncSession = Depends(get_db)) -> dict:
    result = await record_consent(
        db, await _caller_sub(db), body.consent_version
    )
    await db.commit()
    return result


@router.get("/users/me/consent")
async def consents(db: AsyncSession = Depends(get_db)) -> dict:
    return await get_consents(db, await _caller_sub(db))
