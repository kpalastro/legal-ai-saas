"""Link legacy generated_documents to the latest simulation for their case.

Migration 0003 makes a simulation link mandatory for export. Existing rows with
NULL simulation_id become unexportable until linked. Run this once as the owner
before enabling the stricter export path in a database that predates 0003.

Usage:
  uv run python scripts/backfill_document_simulations.py [dsn] [--dry-run]
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

SELECT = text(
    """
    SELECT g.id, g.case_id,
           (SELECT s.id FROM public.simulations s
             WHERE s.case_id = g.case_id ORDER BY s.created_at DESC LIMIT 1)
             AS simulation_id
    FROM public.generated_documents g
    WHERE g.simulation_id IS NULL
    """
)
UPDATE = text(
    "UPDATE public.generated_documents SET simulation_id = :s WHERE id = :id"
)


async def main() -> None:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    dsn = args[0] if args else (
        "postgresql+asyncpg://postgres:postgres@localhost:5434/lexsim"
    )
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            rows = (await conn.execute(SELECT)).mappings().all()
            linkable = [row for row in rows if row["simulation_id"] is not None]
            print(f"{len(rows)} unlinked document(s); {len(linkable)} linkable")
            if dry_run:
                for row in linkable:
                    print(f"  would link {row['id']} -> {row['simulation_id']}")
                return
            for row in linkable:
                await conn.execute(
                    UPDATE, {"s": str(row["simulation_id"]), "id": str(row["id"])}
                )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
