"""Provider factory — the ONLY place `LLM_PROVIDER` is read for wiring."""

from app.config import get_settings
from app.llm.base import LLMProvider


def get_provider() -> LLMProvider:
    s = get_settings()
    if s.llm_provider == "bedrock":
        from app.llm.bedrock import BedrockProvider

        return BedrockProvider()
    from app.llm.ollama import OllamaProvider

    return OllamaProvider()
