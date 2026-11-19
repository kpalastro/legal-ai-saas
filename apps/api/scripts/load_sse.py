"""Load-test the SSE simulation endpoint.

Usage:
  LLM_MODEL=qwen3.5:0.8b uv run python scripts/load_sse.py \
    --token "$JWT" --case-id "$CASE_ID" --concurrency 2 --runs 4

This deliberately does not create data; point it at a disposable case. Rate
limits/quotas may reject excess traffic — that is part of the signal.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx


async def one(client: httpx.AsyncClient, token: str, case_id: str, index: int) -> dict:
    started = time.perf_counter()
    try:
        response = await client.get(
            f"/cases/{case_id}/simulate",
            headers={"Authorization": f"Bearer {token}"},
            timeout=900,
        )
        elapsed = time.perf_counter() - started
        turns = response.text.count("event: turn")
        done = "event: done" in response.text
        return {"run": index, "status": response.status_code, "seconds": round(elapsed, 2),
                "turns": turns, "done": done}
    except Exception as exc:  # noqa: BLE001
        return {"run": index, "status": "error", "seconds": round(time.perf_counter() - started, 2),
                "detail": str(exc)}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(base_url=args.base_url) as client:
        async def guarded(index: int):
            async with semaphore:
                return await one(client, args.token, args.case_id, index)

        results = await asyncio.gather(*(guarded(i) for i in range(args.runs)))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
