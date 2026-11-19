"""Review comments on generated document versions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.organisations import require_case_writer

router = APIRouter(tags=["comments"])


async def _caller_sub(db: AsyncSession) -> str:
    sub = (
        await db.execute(
            text("SELECT current_setting('request.jwt.claims', true)::jsonb ->> 'sub'")
        )
    ).scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=401, detail="no verified identity on the session")
    return str(sub)


async def _doc_case(db: AsyncSession, document_id: str) -> str:
    case_id = (
        await db.execute(
            text("SELECT case_id FROM public.generated_documents WHERE id = :id"),
            {"id": document_id},
        )
    ).scalar_one_or_none()
    if case_id is None:
        raise HTTPException(status_code=404, detail="document not found")
    return str(case_id)


class CommentBody(BaseModel):
    body: str = Field(min_length=1, max_length=5_000)


class ResolveBody(BaseModel):
    resolved: bool = True


@router.get("/documents/{doc_id}/comments")
async def list_comments(doc_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT c.id, c.user_id, u.email, c.body, c.resolved,"
                " c.resolved_at, c.created_at"
                " FROM public.document_comments c"
                " JOIN public.users u ON u.id = c.user_id"
                " WHERE c.document_id = :d ORDER BY c.created_at"
            ),
            {"d": doc_id},
        )
    ).mappings().all()
    return [
        {
            **dict(row),
            "id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
        }
        for row in rows
    ]


@router.post("/documents/{doc_id}/comments", status_code=201)
async def add_comment(
    doc_id: str, body: CommentBody, db: AsyncSession = Depends(get_db)
) -> dict:
    await require_case_writer(db, await _doc_case(db, doc_id))
    row = (
        await db.execute(
            text(
                "INSERT INTO public.document_comments (document_id, user_id, body)"
                " VALUES (:d, :u, :b)"
                " RETURNING id, user_id, body, resolved, created_at"
            ),
            {"d": doc_id, "u": await _caller_sub(db), "b": body.body.strip()},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=500, detail="comment was not created")
    await db.commit()
    return {
        **dict(row),
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


@router.patch("/comments/{comment_id}")
async def resolve_comment(
    comment_id: str, body: ResolveBody, db: AsyncSession = Depends(get_db)
) -> dict:
    document_id = (
        await db.execute(
            text("SELECT document_id FROM public.document_comments WHERE id = :id"),
            {"id": comment_id},
        )
    ).scalar_one_or_none()
    if document_id is None:
        raise HTTPException(status_code=404, detail="comment not found")
    await require_case_writer(db, await _doc_case(db, str(document_id)))
    row = (
        await db.execute(
            text(
                "UPDATE public.document_comments"
                " SET resolved = :r, resolved_at = CASE WHEN :r THEN NOW() ELSE NULL END"
                " WHERE id = :id RETURNING id, resolved, resolved_at"
            ),
            {"r": body.resolved, "id": comment_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="comment not found")
    await db.commit()
    return {
        **dict(row),
        "id": str(row["id"]),
        "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
    }


@router.delete("/comments/{comment_id}")
async def delete_comment(comment_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = (
        await db.execute(
            text(
                "SELECT user_id, document_id FROM public.document_comments WHERE id = :id"
            ),
            {"id": comment_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="comment not found")
    if str(row["user_id"]) != await _caller_sub(db):
        await require_case_writer(db, await _doc_case(db, str(row["document_id"])))
    await db.execute(
        text("DELETE FROM public.document_comments WHERE id = :id"), {"id": comment_id}
    )
    await db.commit()
    return {"id": comment_id, "deleted": True}
