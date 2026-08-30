"""Bedrock provider (Phase 2, dormant in v1). Same audit shape as OllamaProvider —
test_provider_adapter_parity mocks this and compares audit_event_shape payloads.

Region pinning is enforced in config.validate_provider() BEFORE this class ever
instantiates: LLM_PROVIDER=bedrock with region != ap-southeast-2 fails startup
(test_bedrock_region_pinned / S1). No per-call "no-training" flag exists on the
Converse API (SECURITY_CHECKLIST S1.1) — residency is via region + IAM, retention
is via platform policy, so this adapter asserts config instead.
"""

from __future__ import annotations

from app.config import get_settings
from app.llm.base import LLMRequest, LLMResponse


class BedrockProvider:
    def __init__(self) -> None:
        s = get_settings()  # raises ValidationError if region/model not pinned
        self.region = s.bedrock_region
        self.model = s.bedrock_model
        # boto3 client is constructed lazily in complete() so tests can mock it.

    async def health(self) -> bool:
        return self.region == "ap-southeast-2" and self.model is not None

    async def warmup(self) -> None:
        return None  # Bedrock has no model-load semantics; no-op.

    async def complete(self, req: LLMRequest) -> LLMResponse:  # pragma: no cover
        import boto3

        client = boto3.client("bedrock-runtime", region_name=self.region)
        resp = client.converse(
            modelId=self.model,
            system=[{"text": req.system}],
            messages=[{"role": "user", "content": [{"text": req.user}]}],
            inferenceConfig={
                "maxTokens": req.max_tokens,
                "temperature": req.options.get("temperature", 0.3),
            },
        )
        out = resp["output"]["message"]["content"][0]["text"]
        usage = resp.get("usage", {})
        return LLMResponse(
            text=out,
            model=self.model or "",
            prompt_tokens=usage.get("inputTokens"),
            completion_tokens=usage.get("outputTokens"),
        )

    # COMPLIANCE_NOTE (3.3 / APP 8) — the Converse calls above rely on the
    # ACCOUNT-level model-training opt-out (AWS org settings / AI services
    # opt-out policies). There is no per-request no-training flag on Converse;
    # before any real case data (Phase 2), @security must assert the opt-out
    # policy is attached in ap-southeast-2 — otherwise user case content could
    # be used for service improvement, which violates the documented posture.
    # Until asserted, this provider must stay dormant behind ollama (v1 default).
