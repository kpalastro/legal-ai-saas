"""Per-role sampler presets — supervisor's Ollama Runtime Pitfalls §3/§4, verified live
on this machine 30 Aug 2026. Do not port OpenRouter defaults; keep penalties unset."""

from app.agents.debate_state_machine import AgentRole

# temperature 0.15 for JUDGE (determinism-leaning), 0.3 for the two advocates.
ROLE_OPTIONS: dict[AgentRole, dict] = {
    AgentRole.JUDGE: {
        "temperature": 0.15,
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.1,
        "num_ctx": 32768,
        "num_predict": 2048,
    },
    AgentRole.USER_ADVOCATE: {
        "temperature": 0.3,
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.1,
        "num_ctx": 32768,
        "num_predict": 2048,
    },
    AgentRole.OPPONENT: {
        "temperature": 0.3,
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.1,
        "num_ctx": 32768,
        "num_predict": 2048,
    },
}

# JUDGE needs a FIXED seed — temperature=0 alone still samples via the /v1 path
# (pitfall §4), so determinism tests pin this too.
JUDGE_SEED = 42


def options_for(role: AgentRole) -> dict:
    return dict(ROLE_OPTIONS[role])


def seed_for(role: AgentRole) -> int | None:
    return JUDGE_SEED if role == AgentRole.JUDGE else None
