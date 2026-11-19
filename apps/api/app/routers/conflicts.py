"""Conflict-check register and search across matter parties.

A conflict check is a professional-obligation control, not legal advice: it
surfaces name matches in the caller's visible matters and the organisation's
register. A human must resolve them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

router = APIRouter(tags=["conflicts"])


async def _caller_sub(db: AsyncSession) -> str:
    sub = (
        await db.execute(
            text("SELECT current_setting('request.jwt.claims', true)::jsonb ->> 'sub'")
        )
    ).scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=401, detail="no verified identity on the session")
    return str(sub)


async def _require_org_member(db: AsyncSession, org_id: str) -> None:
    ok = (
        await db.execute(
            text("SELECT public.is_org_member(:o) AS ok"), {"o": org_id}
        )
    ).scalar_one_or_none()
    if ok is not True:
        raise HTTPException(status_code=404, detail="organisation not found")


async def _require_org_writer(db: AsyncSession, org_id: str) -> None:
    ok = (
        await db.execute(
            text("SELECT public.is_org_writer(:o) AS ok"), {"o": org_id}
        )
    ).scalar_one_or_none()
    if ok is not True:
        raise HTTPException(status_code=403, detail="writer role required")


@router.get("/conflicts/check")
async def conflict_check(
    name: str = Query(min_length=2, max_length=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    pattern = f"%{name.strip().lower()}%"
    matter_rows = (
        await db.execute(
            text(
                """
                SELECT c.id AS case_id, c.title, p->>'name' AS party,
                       COALESCE(p->>'role', 'party') AS role, 'case' AS source
                FROM public.cases c
                CROSS JOIN LATERAL jsonb_array_elements(c.parties) p
                WHERE lower(p->>'name') LIKE :pattern
                """
            ),
            {"pattern": pattern},
        )
    ).mappings().all()
    register_rows = (
        await db.execute(
            text(
                """
                SELECT id, org_id, party_name, matter_ref, note, 'register' AS source
                FROM public.conflicts
                WHERE lower(party_name) LIKE :pattern
                """
            ),
            {"pattern": pattern},
        )
    ).mappings().all()
    matches = [
        {
            "source": "case",
            "case_id": str(row["case_id"]),
            "title": row["title"],
            "party": row["party"],
            "role": row["role"],
        }
        for row in matter_rows
    ] + [
        {
            "source": "register",
            "id": str(row["id"]),
            "org_id": str(row["org_id"]),
            "party": row["party_name"],
            "matter_ref": row["matter_ref"],
            "note": row["note"],
        }
        for row in register_rows
    ]
    return {
        "query": name,
        "matches": matches,
        "note": "Name matches only. A human must resolve any potential conflict.",
    }


class ConflictBody(BaseModel):
    org_id: str
    party_name: str = Field(min_length=2, max_length=300)
    matter_ref: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2_000)


@router.post("/conflicts", status_code=201)
async def add_conflict(body: ConflictBody, db: AsyncSession = Depends(get_db)) -> dict:
    await _require_org_writer(db, body.org_id)
    row = (
        await db.execute(
            text(
                "INSERT INTO public.conflicts"
                " (org_id, party_name, matter_ref, note, created_by)"
                " VALUES (:o, :p, :m, :n, :u)"
                " RETURNING id, org_id, party_name, matter_ref, note, created_at"
            ),
            {
                "o": body.org_id,
                "p": body.party_name.strip(),
                "m": body.matter_ref,
                "n": body.note,
                "u": await _caller_sub(db),
            },
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=500, detail="conflict entry was not created")
    await db.commit()
    return {
        **dict(row),
        "id": str(row["id"]),
        "org_id": str(row["org_id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


@router.get("/organisations/{org_id}/conflicts")
async def list_conflicts(org_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    await _require_org_member(db, org_id)
    rows = (
        await db.execute(
            text(
                "SELECT id, party_name, matter_ref, note, created_at"
                " FROM public.conflicts WHERE org_id = :o ORDER BY created_at DESC"
            ),
            {"o": org_id},
        )
    ).mappings().all()
    return [
        {
            **dict(row),
            "id": str(row["id"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]


@router.delete("/conflicts/{conflict_id}")
async def delete_conflict(conflict_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    org_id = (
        await db.execute(
            text("SELECT org_id FROM public.conflicts WHERE id = :id"),
            {"id": conflict_id},
        )
    ).scalar_one_or_none()
    if org_id is None:
        raise HTTPException(status_code=404, detail="conflict entry not found")
    await _require_org_writer(db, str(org_id))
    await db.execute(text("DELETE FROM public.conflicts WHERE id = :id"), {"id": conflict_id})
    await db.commit()
    return {"id": conflict_id, "deleted": True}
