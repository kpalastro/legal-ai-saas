"""Organisation/membership operations (professional-tier RBAC).

RLS is the boundary; these helpers add the business rules RLS cannot express:
one immutable owner, no self-escalation to owner, and only the case creator can
share/unshare a matter with an organisation.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import text

ASSIGNABLE_ROLES = {"admin", "lawyer", "paralegal", "viewer"}
WRITER_ROLES = {"owner", "admin", "lawyer", "paralegal"}


async def require_case_writer(db, case_id: str) -> None:
    """Clean 403 before a write hits an RLS WITH CHECK violation."""
    ok = (
        await db.execute(
            text("SELECT public.case_writable(:c) AS ok"), {"c": case_id}
        )
    ).scalar_one_or_none()
    if ok is not True:
        raise HTTPException(
            status_code=403,
            detail="write access required for this matter (viewer or non-member)",
        )


async def my_role(db, org_id: str, user_id: str) -> str | None:
    return (
        await db.execute(
            text(
                "SELECT role FROM public.memberships"
                " WHERE org_id = :o AND user_id = :u"
            ),
            {"o": org_id, "u": user_id},
        )
    ).scalar_one_or_none()


async def require_member(db, org_id: str, user_id: str) -> str:
    role = await my_role(db, org_id, user_id)
    if role is None:
        raise HTTPException(status_code=404, detail="organisation not found")
    return role


async def require_admin(db, org_id: str, user_id: str) -> str:
    role = await require_member(db, org_id, user_id)
    if role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="admin or owner role required")
    return role


async def create_org(db, user_id: str, name: str) -> dict:
    org = (
        await db.execute(
            text(
                "INSERT INTO public.organisations (name, owner_id)"
                " VALUES (:n, :u) RETURNING id, name, owner_id, created_at"
            ),
            {"n": name, "u": user_id},
        )
    ).mappings().first()
    if org is None:
        raise HTTPException(status_code=500, detail="organisation was not created")
    await db.execute(
        text(
            "INSERT INTO public.memberships (org_id, user_id, role)"
            " VALUES (:o, :u, 'owner')"
        ),
        {"o": str(org["id"]), "u": user_id},
    )
    return {
        "id": str(org["id"]),
        "name": org["name"],
        "owner_id": str(org["owner_id"]),
        "role": "owner",
        "created_at": org["created_at"].isoformat() if org["created_at"] else None,
    }


async def list_orgs(db, user_id: str) -> list[dict]:
    rows = (
        await db.execute(
            text(
                """
                SELECT o.id, o.name, o.owner_id, o.created_at,
                       (SELECT m.role FROM public.memberships m
                         WHERE m.org_id = o.id AND m.user_id = :u) AS role,
                       (SELECT count(*) FROM public.memberships m
                         WHERE m.org_id = o.id) AS member_count
                FROM public.organisations o
                ORDER BY o.created_at
                """
            ),
            {"u": user_id},
        )
    ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "owner_id": str(r["owner_id"]),
            "role": r["role"],
            "member_count": int(r["member_count"]),
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


async def get_org(db, org_id: str, user_id: str) -> dict:
    await require_member(db, org_id, user_id)
    row = (
        await db.execute(
            text(
                "SELECT id, name, owner_id, created_at"
                " FROM public.organisations WHERE id = :o"
            ),
            {"o": org_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="organisation not found")
    members = (
        await db.execute(
            text(
                "SELECT m.user_id, m.role, m.created_at, u.email"
                " FROM public.memberships m"
                " JOIN public.users u ON u.id = m.user_id"
                " WHERE m.org_id = :o ORDER BY m.created_at"
            ),
            {"o": org_id},
        )
    ).mappings().all()
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "owner_id": str(row["owner_id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "members": [
            {
                "user_id": str(m["user_id"]),
                "email": m["email"],
                "role": m["role"],
                "created_at": m["created_at"].isoformat() if m["created_at"] else None,
            }
            for m in members
        ],
    }


async def add_member(db, org_id: str, actor_id: str, email: str, role: str) -> dict:
    await require_admin(db, org_id, actor_id)
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"role must be one of {sorted(ASSIGNABLE_ROLES)} (owner is unique)",
        )
    target = (
        await db.execute(
            text("SELECT id, email FROM public.users WHERE email = :e"), {"e": email}
        )
    ).mappings().first()
    if target is None:
        raise HTTPException(
            status_code=404,
            detail="user not found — they must sign in at least once before being added",
        )
    await db.execute(
        text(
            "INSERT INTO public.memberships (org_id, user_id, role)"
            " VALUES (:o, :u, :r)"
            " ON CONFLICT (org_id, user_id) DO UPDATE SET role = EXCLUDED.role"
        ),
        {"o": org_id, "u": str(target["id"]), "r": role},
    )
    return {
        "org_id": org_id,
        "user_id": str(target["id"]),
        "email": target["email"],
        "role": role,
    }


async def update_member(db, org_id: str, actor_id: str, target_id: str, role: str) -> dict:
    await require_admin(db, org_id, actor_id)
    if role not in ASSIGNABLE_ROLES:
        raise HTTPException(status_code=422, detail="owner role cannot be assigned")
    target_role = await my_role(db, org_id, target_id)
    if target_role is None:
        raise HTTPException(status_code=404, detail="member not found")
    if target_role == "owner":
        raise HTTPException(status_code=409, detail="the owner's role is immutable")
    await db.execute(
        text(
            "UPDATE public.memberships SET role = :r"
            " WHERE org_id = :o AND user_id = :u"
        ),
        {"r": role, "o": org_id, "u": target_id},
    )
    return {"org_id": org_id, "user_id": target_id, "role": role}


async def remove_member(db, org_id: str, actor_id: str, target_id: str) -> dict:
    await require_admin(db, org_id, actor_id)
    target_role = await my_role(db, org_id, target_id)
    if target_role is None:
        raise HTTPException(status_code=404, detail="member not found")
    if target_role == "owner":
        raise HTTPException(status_code=409, detail="the owner cannot be removed")
    await db.execute(
        text("DELETE FROM public.memberships WHERE org_id = :o AND user_id = :u"),
        {"o": org_id, "u": target_id},
    )
    return {"org_id": org_id, "user_id": target_id, "removed": True}


async def share_case(db, case_id: str, user_id: str, org_id: str) -> dict:
    row = (
        await db.execute(
            text("SELECT user_id FROM public.cases WHERE id = :c"), {"c": case_id}
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="case not found")
    if str(row["user_id"]) != user_id:
        raise HTTPException(
            status_code=403, detail="only the case creator can share or unshare it"
        )
    writer = (
        await db.execute(
            text("SELECT public.is_org_writer(:o) AS ok"), {"o": org_id}
        )
    ).scalar_one_or_none()
    if writer is not True:
        raise HTTPException(
            status_code=403, detail="you need a writer role in the target organisation"
        )
    updated = (
        await db.execute(
            text(
                "UPDATE public.cases SET org_id = :o WHERE id = :c"
                " RETURNING id, org_id"
            ),
            {"o": org_id, "c": case_id},
        )
    ).mappings().first()
    if updated is None:
        raise HTTPException(status_code=404, detail="case not found")
    return {"id": str(updated["id"]), "org_id": str(updated["org_id"])}


async def unshare_case(db, case_id: str, user_id: str) -> dict:
    row = (
        await db.execute(
            text("SELECT user_id FROM public.cases WHERE id = :c"), {"c": case_id}
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="case not found")
    if str(row["user_id"]) != user_id:
        raise HTTPException(
            status_code=403, detail="only the case creator can share or unshare it"
        )
    await db.execute(
        text("UPDATE public.cases SET org_id = NULL WHERE id = :c"), {"c": case_id}
    )
    return {"id": case_id, "org_id": None}


async def record_consent(db, user_id: str, consent_version: str) -> dict:
    await db.execute(
        text(
            "INSERT INTO public.consents (user_id, consent_version)"
            " VALUES (:u, :v) ON CONFLICT (user_id, consent_version) DO NOTHING"
        ),
        {"u": user_id, "v": consent_version},
    )
    return await get_consents(db, user_id, consent_version)


async def get_consents(db, user_id: str, version: str | None = None) -> dict:
    query = "SELECT consent_version, accepted_at FROM public.consents WHERE user_id = :u"
    params: dict = {"u": user_id}
    if version:
        query += " AND consent_version = :v"
        params["v"] = version
    rows = (await db.execute(text(query + " ORDER BY accepted_at"), params)).mappings().all()
    return {
        "user_id": user_id,
        "consents": [
            {
                "consent_version": r["consent_version"],
                "accepted_at": r["accepted_at"].isoformat() if r["accepted_at"] else None,
            }
            for r in rows
        ],
    }
