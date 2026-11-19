"""Minimal in-process Prometheus metrics.

No external sink is configured in v1. These counters make the money path
visible (`/metrics`): request mix, LLM calls and token usage. They reset on
process restart, which is correct for a single-instance dev/edge deployment; a
multi-instance prod should scrape each process or use OpenTelemetry.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from threading import Lock

_LOCK = Lock()
_HTTP: Counter[tuple[str, str, str]] = Counter()
_LLM: Counter[str] = Counter()
_PROMPT_TOKENS: Counter[str] = Counter()
_COMPLETION_TOKENS: Counter[str] = Counter()
_STARTED = time.time()
_UUID = re.compile(r"/[0-9a-fA-F-]{36}")


def _normalise_path(path: str) -> str:
    return _UUID.sub("/{id}", path)


def observe_http(method: str, path: str, status: int) -> None:
    with _LOCK:
        _HTTP[(method, _normalise_path(path), str(status))] += 1


def observe_llm(model: str, prompt_tokens: int | None, completion_tokens: int | None) -> None:
    with _LOCK:
        _LLM[model] += 1
        _PROMPT_TOKENS[model] += int(prompt_tokens or 0)
        _COMPLETION_TOKENS[model] += int(completion_tokens or 0)


def render() -> str:
    lines = [
        "# HELP lexsim_uptime_seconds Process uptime.",
        "# TYPE lexsim_uptime_seconds gauge",
        f"lexsim_uptime_seconds {time.time() - _STARTED:.1f}",
        "# HELP lexsim_http_requests_total HTTP requests by method/path/status.",
        "# TYPE lexsim_http_requests_total counter",
    ]
    with _LOCK:
        for (method, path, status), count in sorted(_HTTP.items()):
            lines.append(
                f'lexsim_http_requests_total{{method="{method}",path="{path}",'
                f'status="{status}"}} {count}'
            )
        lines.extend(
            [
                "# HELP lexsim_llm_calls_total LLM completions.",
                "# TYPE lexsim_llm_calls_total counter",
            ]
        )
        for model, count in sorted(_LLM.items()):
            lines.append(f'lexsim_llm_calls_total{{model="{model}"}} {count}')
        lines.extend(
            [
                "# HELP lexsim_llm_prompt_tokens_total Prompt tokens.",
                "# TYPE lexsim_llm_prompt_tokens_total counter",
            ]
        )
        for model, count in sorted(_PROMPT_TOKENS.items()):
            lines.append(f'lexsim_llm_prompt_tokens_total{{model="{model}"}} {count}')
        lines.extend(
            [
                "# HELP lexsim_llm_completion_tokens_total Completion tokens.",
                "# TYPE lexsim_llm_completion_tokens_total counter",
            ]
        )
        for model, count in sorted(_COMPLETION_TOKENS.items()):
            lines.append(f'lexsim_llm_completion_tokens_total{{model="{model}"}} {count}')
    return "\n".join(lines) + "\n"


def reset() -> None:
    """Test helper."""
    with _LOCK:
        _HTTP.clear()
        _LLM.clear()
        _PROMPT_TOKENS.clear()
        _COMPLETION_TOKENS.clear()
