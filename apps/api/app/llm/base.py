"""LLM provider abstraction (TECH_STACK.md Localhost v1).

`LLM_PROVIDER=ollama|bedrock` env switch; the debate engine depends only on
`LLMProvider.complete()`. Phase 2 Bedrock swap = one-line env change.

Both adapters emit the same audit event shape — test_provider_adapter_parity
(TEST_PLAN 5.3) asserts byte-identical audit_log payloads across providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    # Per-role sampler/seed pins come from app.llm.presets (supervisor pitfalls §3/§4).
    options: dict
    max_tokens: int
    seed: int | None = None


@dataclass(frozen=True)
class LLMResponse:
    text: str  # <think> traces already stripped (pitfall §4)
    model: str
    # Same shape for both providers — the audit_parity() contract below.
    prompt_tokens: int | None
    completion_tokens: int | None


class LLMProvider(Protocol):
    async def complete(self, req: LLMRequest) -> LLMResponse: ...
    async def health(self) -> bool: ...
    async def warmup(self) -> None: ...


def audit_event_shape(req: LLMRequest, resp: LLMResponse) -> dict:
    """Canonical audit_log payload — IDENTICAL across providers (parity test target)."""
    return {
        "model": resp.model,
        "prompt_sha": _sha(req.system + "\n" + req.user),
        "response_sha": _sha(resp.text),
        "prompt_tokens": resp.prompt_tokens,
        "completion_tokens": resp.completion_tokens,
    }


def _sha(s: str) -> str:
    import hashlib

    return hashlib.sha256(s.encode()).hexdigest()[:16]
