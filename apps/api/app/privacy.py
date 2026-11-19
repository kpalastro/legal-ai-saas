"""De-identification (APP 12/13) without breaking the append-only audit trail.

Deleting a user/case would cascade into `audit_log`, whose DELETE trigger is
intentional. Instead, case content is overwritten with tombstones while the audit
rows and their `content_ref` chain remain intact for LPP/legal-hold obligations.
Raw uploads are removed from disk. The GoTrue identity is a separate system and
must be deleted via the auth admin API/console.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.config import get_settings


async def _document_paths(conn, case_id: str) -> list[str]:
    rows = (
        await conn.execute(
            text("SELECT file_path FROM public.documents WHERE case_id = :c"),
            {"c": case_id},
        )
    ).scalars().all()
    return [str(path) for path in rows if path]


async def deidentify_case(conn, case_id: str) -> list[str]:
    """Overwrite one case's content with tombstones; return upload paths to delete."""
    paths = await _document_paths(conn, case_id)

    # Export gate: turn exported off first so the trigger does not re-check a
    # simulation attestation that is about to be cleared.
    await conn.execute(
        text(
            "UPDATE public.generated_documents"
            " SET content = '[erased]', citations = '[]'::jsonb,"
            "     user_reviewed = false, exported = false,"
            "     export_blocked_reason = 'erased'"
            " WHERE case_id = :c"
        ),
        {"c": case_id},
    )
    await conn.execute(
        text(
            "UPDATE public.simulations"
            " SET debate_transcript = '[]'::jsonb, outcome_prediction = NULL,"
            "     weakness_report = NULL, hallucination_score = NULL,"
            "     user_attestation = false, user_attested_at = NULL"
            " WHERE case_id = :c"
        ),
        {"c": case_id},
    )
    await conn.execute(
        text(
            "UPDATE public.documents"
            " SET original_filename = '[erased]', extracted_text = NULL,"
            "     sha256 = NULL, file_path = '[erased]'"
            " WHERE case_id = :c"
        ),
        {"c": case_id},
    )
    await conn.execute(
        text("DELETE FROM public.document_chunks WHERE case_id = :c"), {"c": case_id}
    )
    await conn.execute(
        text("DELETE FROM public.authority_snapshots WHERE case_id = :c"), {"c": case_id}
    )
    await conn.execute(
        text("DELETE FROM public.deadlines WHERE case_id = :c"), {"c": case_id}
    )
    await conn.execute(
        text(
            "UPDATE public.cases"
            " SET title = '[erased]', description = NULL,"
            "     parties = '[]'::jsonb, issues = '[]'::jsonb,"
            "     relief_sought = NULL, case_number = NULL,"
            "     erased_at = COALESCE(erased_at, NOW()), status = 'archived'"
            " WHERE id = :c"
        ),
        {"c": case_id},
    )
    return paths


async def erase_user(conn, user_id: str) -> tuple[list[str], int]:
    """De-identify every case for a user and tombstone the profile.

    Refuses if any case is under legal hold (caller turns that into 409).
    """
    rows = (
        await conn.execute(
            text("SELECT id, legal_hold FROM public.cases WHERE user_id = :u"),
            {"u": user_id},
        )
    ).mappings().all()
    if any(row["legal_hold"] for row in rows):
        raise PermissionError("a case is under legal hold; release it before erasure")

    paths: list[str] = []
    for row in rows:
        paths.extend(await deidentify_case(conn, str(row["id"])))

    await conn.execute(
        text(
            "UPDATE public.users"
            " SET email = 'erased+' || :u || '@invalid',"
            "     subscription_tier = NULL, erased_at = NOW()"
            " WHERE id = :u"
        ),
        {"u": user_id},
    )
    return paths, len(rows)


def delete_uploads(paths: list[str]) -> int:
    """Delete raw uploads, but only inside the configured storage root."""
    root = Path(get_settings().storage_dir).resolve()
    removed = 0
    for raw in paths:
        try:
            path = Path(raw).resolve()
            if path.is_relative_to(root):
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            continue
    return removed


async def retention_deidentify(conn, cutoff) -> tuple[int, list[str]]:
    """De-identify cases past the retention window (no legal hold)."""
    rows = (
        await conn.execute(
            text(
                "SELECT id FROM public.cases"
                " WHERE created_at < :cutoff AND legal_hold = FALSE"
                " AND status <> 'archived'"
            ),
            {"cutoff": cutoff},
        )
    ).scalars().all()
    paths: list[str] = []
    for case_id in rows:
        paths.extend(await deidentify_case(conn, str(case_id)))
    return len(rows), paths
