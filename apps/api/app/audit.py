"""Append-only audit writer for C1/G5 + checklist 3.2 (as patched by @compliance).

Prompts/responses persist VERBATIM (local `audit_content`, referenced via
content_ref — hashes are tamper-EVIDENCE, not an LPP trail). One statement, one
transaction: the audit row and its content land atomically, and the append-only
triggers (migration 0001) reject any UPDATE/DELETE on either table. This module
is the ONLY write path; nothing else should INSERT into audit_log/audit_content.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def write_audit_row(
    db: AsyncSession,
    *,
    case_id: str | None,
    user_id: str,
    event_type: str,
    model_id: str,
    prompt_text: str,
    response_text: str,
    prompt_sha: str | None = None,
    response_sha: str | None = None,
    prompt_version: str | None = None,
    model_digest: str | None = None,
) -> None:
    """Write content + audit row atomically (CTE guarantees the pairing).

    case_id may be NULL for account-level events (e.g. erasure/export); the
    audit INSERT policy only requires user_id = auth.uid().
    """
    ref = f"inline:{prompt_sha or ''}:{response_sha or ''}"
    await db.execute(
        text(
            "WITH new_content AS ("
            "  INSERT INTO public.audit_content (prompt_text, response_text)"
            "  VALUES (:p, :r) RETURNING id"
            ")"
            " INSERT INTO public.audit_log (case_id, user_id, event_type, model_id,"
            "   prompt_ref, response_ref, content_ref, prompt_version, model_digest)"
            " SELECT :case_id, :user_id, :event_type, :model_id, :prompt_ref,"
            "   :response_ref, id, :prompt_version, :model_digest FROM new_content"
        ),
        dict(
            p=prompt_text,
            r=response_text,
            case_id=case_id,
            user_id=user_id,
            event_type=event_type,
            model_id=model_id,
            prompt_ref=ref,
            response_ref=ref,
            prompt_version=prompt_version,
            model_digest=model_digest,
        ),
    )