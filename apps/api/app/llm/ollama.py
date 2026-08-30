"""Ollama provider — native /api/chat on localhost:11434 (NOT the /v1 layer).

v1 scope is ollama-only, so using the native endpoint here while
BedrockProvider keeps the Converse shape doesn't break the LLM_PROVIDER env
switch — the debate engine only ever sees LLMProvider.complete().

WHY /api/chat — verified live on this machine 30 Aug 2026 (qwen3.5:0.8b/fast):
  • On /v1, the qwen3.5 family's thinking goes to a SEPARATE `reasoning` field
    while `content` returns EMPTY until the thinking budget is spent — and
    `max_tokens` counts reasoning tokens, so the pinned per-turn budget was
    consumed by invisible thoughts and every debate turn returned blank.
    `think:false`, `chat_template_kwargs.think:false`, and tags
    strip-after-the-fact could not fix it from the client side over /v1.
  • On /api/chat, `think:false` disables thinking server-side, options
    (`num_ctx`/`num_predict`/`seed`/samplers) are honored, and token usage
    (`prompt_eval_count`/`eval_count`) is exposed.
  • warm-up + num_ctx/num_predict + seed pins from TECH_STACK.md "Ollama Runtime
    Pitfalls" §1/§2/§4 are applied the same way — just over the endpoint that
    actually respects them.

test_ollama_local_only (3.3): talks ONLY to ollama_base_url (host loopback or
host.docker.internal) — never 0.0.0.0, never from a browser (SECURITY S4.3).
"""

from __future__ import annotations

import re

import httpx

from app.config import get_settings
from app.llm.base import LLMRequest, LLMResponse

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)  # belt-and-braces strip


class OllamaProvider:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        s = get_settings()
        self.base_url = (base_url or s.ollama_base_url).rstrip("/")
        self.model = model or s.llm_model
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(180.0))

    async def health(self) -> bool:
        """Fail-fast readiness (S4.1): daemon reachable AND the model warm this boot
        (a 200 on /api/tags alone proves nothing)."""
        try:
            (await self._client.get("/api/tags")).raise_for_status()
            ps = (await self._client.get("/api/ps")).json().get("models", [])
        except httpx.HTTPError:
            return False
        return any(m["name"].split(":")[0] == self.model.split(":")[0] for m in ps)

    async def warmup(self) -> None:
        """Pin the model in memory (pitfall §1: keep_alive=-1) so debate turn-1
        never pays the 6.6 GB load and SSE never shows a blank first frame."""
        await self._client.post(
            "/api/generate",
            json={
                "model": self.model,
                "prompt": "warmup",
                "stream": False,
                "keep_alive": -1,
                "think": False,
                "options": {"num_predict": 1, "num_ctx": 512},
            },
        )

    async def complete(self, req: LLMRequest) -> LLMResponse:
        """One chat turn. options carry the 32 GB RAM ceiling + sampler pins; JUDGE
        requests also carry the fixed seed (pitfall §4)."""
        options = dict(req.options)  # num_ctx=32768, num_predict=2048, samplers
        if req.seed is not None:
            options["seed"] = req.seed  # only JUDGE — pitfall §4 determinism
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user},
            ],
            "stream": False,
            "think": False,              # server-side thinking OFF (verified /v1 bug)
            "keep_alive": -1,            # keep resident across turns
            "options": options,
        }
        r = await self._client.post("/api/chat", json=body)
        r.raise_for_status()
        data = r.json()
        text = _THINK_RE.sub("", data.get("message", {}).get("content", "")).strip()
        return LLMResponse(
            text=text,
            model=self.model,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )
