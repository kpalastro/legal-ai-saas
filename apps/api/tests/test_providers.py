"""Provider tests: config guards, local-only posture, parity-shaped audit payloads.
Compliance-gate tiers are stub-deterministic here (TEST_PLAN nondeterminism rules)."""

import pytest

from app.config import Settings
from app.llm.base import LLMRequest, LLMResponse, audit_event_shape
from app.llm.ollama import OllamaProvider
from app.llm.presets import JUDGE_SEED, options_for, seed_for
from app.agents.debate_state_machine import AgentRole


def test_bedrock_region_pinned() -> None:
    """S1: LLM_PROVIDER=bedrock with a wrong region fails startup."""
    s = Settings(llm_provider="bedrock", bedrock_region="us-east-1",
                 bedrock_model="openai.gpt-oss-120b-1:0")
    with pytest.raises(Exception):
        s.validate_provider()


def test_bedrock_rejects_cross_region_model() -> None:
    """G8: an apac./global. model ID is refused even with region correct."""
    s = Settings(llm_provider="bedrock", bedrock_region="ap-southeast-2",
                 bedrock_model="apac.openai.gpt-oss-120b-1:0")
    with pytest.raises(Exception):
        s.validate_provider()


def test_v1_default_is_ollama_local() -> None:
    s = Settings()
    s.validate_provider()
    assert s.llm_provider == "ollama"
    assert "localhost" in s.ollama_base_url or "host.docker.internal" in s.ollama_base_url


def test_sampler_presets_carry_ram_caps() -> None:
    """Supervisor pitfall §2 regression net: every role gets num_ctx + num_predict."""
    for role in AgentRole:
        opts = options_for(role)
        assert opts["num_ctx"] == 32768
        assert opts["num_predict"] == 2048
        assert "presence_penalty" not in opts and "frequency_penalty" not in opts


def test_judge_seed_pinned() -> None:
    assert seed_for(AgentRole.JUDGE) == JUDGE_SEED
    assert seed_for(AgentRole.USER_ADVOCATE) is None


def test_request_carries_ctx_seed_and_think_off(monkeypatch) -> None:
    """3.3 + supervisor pitfall §2 net: request asserts num_ctx/num_predict present on
    every call; JUDGE seed pinned; think disabled (verified /v1 blank-content bug)."""
    captured: dict = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"message": {"content": "<think>x</think>verdict"},
                    "prompt_eval_count": 10, "eval_count": 5}

    class FakeClient:
        async def post(self, url, json):
            captured.update({"url": url, "body": json})
            return FakeResp()

    p = OllamaProvider.__new__(OllamaProvider)
    p.base_url, p.model, p._client = "http://localhost:11434", "qwen3.5:latest", FakeClient()

    import asyncio
    req = LLMRequest(system="s", user="u", options=options_for(AgentRole.JUDGE),
                     max_tokens=2048, seed=42)
    resp = asyncio.new_event_loop().run_until_complete(p.complete(req))

    assert captured["url"] == "/api/chat"               # NOT /v1 (thinking-budget bug)
    assert captured["body"]["think"] is False
    assert captured["body"]["keep_alive"] == -1
    assert captured["body"]["options"]["num_ctx"] == 32768
    assert captured["body"]["options"]["num_predict"] == 2048
    assert captured["body"]["options"]["seed"] == 42    # JUDGE determinism (pitfall §4)
    assert resp.text == "verdict"                       # think traces stripped
    assert resp.prompt_tokens == 10 and resp.completion_tokens == 5


def test_audit_parity_shape() -> None:
    """5.3 net: same fixture through both providers' LLMResponse -> identical audit."""
    req = LLMRequest(system="sys", user="usr", options={}, max_tokens=1)
    ollama_resp = LLMResponse(text="out", model="qwen3.5:latest",
                              prompt_tokens=10, completion_tokens=5)
    bedrock_resp = LLMResponse(text="out", model="openai.gpt-oss-120b-1:0",
                               prompt_tokens=10, completion_tokens=5)
    a, b = audit_event_shape(req, ollama_resp), audit_event_shape(req, bedrock_resp)
    # every field except model identity must match byte-for-byte
    assert {k: v for k, v in a.items() if k != "model"} == {k: v for k, v in b.items() if k != "model"}
    assert set(a) == set(b) == {"model", "prompt_sha", "response_sha",
                                "prompt_tokens", "completion_tokens"}
