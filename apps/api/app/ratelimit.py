"""Small fixed-window rate limiter (Redis-backed, in-memory fallback).

Applied to the expensive/abusable endpoints: simulation runs, document
generation, citation verification and billing checkout. Redis is the shared
counter in compose/prod; if it is unavailable the process falls back to memory
(best-effort, per-worker) rather than failing the request.
"""

from __future__ import annotations

import asyncio
import time

import redis.asyncio as redis
from fastapi import HTTPException, Request

from app.config import get_settings

_memory: dict[str, tuple[int, float]] = {}
_memory_lock = asyncio.Lock()
_redis_client: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis_client


async def consume_memory(key: str, limit: int, window: int) -> tuple[bool, int]:
    """In-memory fixed window. Public for tests."""
    async with _memory_lock:
        now = time.monotonic()
        count, reset = _memory.get(key, (0, now + window))
        if now >= reset:
            count, reset = 0, now + window
        count += 1
        _memory[key] = (count, reset)
        return count <= limit, max(0, int(reset - now))


async def consume_redis(key: str, limit: int, window: int) -> tuple[bool, int]:
    client = _client()
    pipe = client.pipeline()
    pipe.incr(key)
    pipe.expire(key, window, nx=True)
    count, _ = await pipe.execute()
    ttl = await client.ttl(key)
    return int(count) <= limit, max(0, int(ttl))


async def check(request: Request, name: str, limit: int, window: int) -> None:
    # Client IP, not user id: auth happens later in get_db, and the limit must
    # still protect unauthenticated/forged-token traffic.
    ip = request.client.host if request.client else "unknown"
    key = f"rl:{name}:{ip}"
    try:
        allowed, retry_after = await consume_redis(key, limit, window)
    except Exception:
        allowed, retry_after = await consume_memory(key, limit, window)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded — retry later",
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit(name: str, limit: int, window: int):
    async def dependency(request: Request) -> None:
        await check(request, name, limit, window)

    return dependency
