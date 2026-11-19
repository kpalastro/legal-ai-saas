"""LexSim AI API — config (12-factor, pydantic-settings).

v1 = fully local (LLM_PROVIDER=ollama). Phase 2 = LLM_PROVIDER=bedrock, zero code
change via the provider adapter (app/llm/).
"""

from functools import lru_cache

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# Bedrock allowed model IDs: regional only — never global./apac./us./eu. prefixes
# (SECURITY_CHECKLIST APP-8 gate G8). Asserted only when LLM_PROVIDER=bedrock.
ALLOWED_BEDROCK_MODEL_IDS = frozenset(
    {
        "openai.gpt-oss-120b-1:0",
        "anthropic.claude-sonnet-5:0",  # confirm exact regional ID before enabling
    }
)

# v1 local models on this machine's Ollama daemon (verified /api/tags 30 Aug 2026).
OLLAMA_MODEL_DEFAULT = "qwen3.5:latest"
OLLAMA_MODEL_CI = "qwen3.5:0.8b"  # CI smoke tier
OLLAMA_MODEL_FAST = "qwen3.5-fast:latest"  # pytest/arq integration tier

# Supervisor-verified runtime caps (32 GB machine, 6.6 GB weights):
LLM_NUM_CTX = 32768        # KV-cache ceiling — do NOT raise without re-verifying RAM
LLM_NUM_PREDICT = 2048     # per-turn generation cap


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    # --- LLM provider switch (Phase 2 swaps ollama -> bedrock) ---
    llm_provider: str = "ollama"  # "ollama" | "bedrock"
    llm_model: str = OLLAMA_MODEL_DEFAULT
    ollama_base_url: str = "http://localhost:11434"  # host.docker.internal inside compose

    # Bedrock (Phase 2; dormant in v1 but guarded — test_bedrock_region_pinned)
    bedrock_region: str | None = None
    bedrock_model: str | None = None

    # --- data plane ---
    # Default matches the compose stack (infra/docker-compose.yml publishes
    # postgres:17 on :5434 — NOT :5432, which on this machine belongs to a foreign
    # project's container that just happens to accept the same credentials).
    # Override with DATABASE_URL outside compose.
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5434/lexsim"
    redis_url: str = "redis://localhost:6379/0"

    # --- auth (self-hosted GoTrue on :9999 locally; hosted Supabase later) ---
    gotrue_url: str = "http://localhost:9999"
    supabase_jwt_secret: str = "dev-only-jwt-secret-change-me"
    # Optional admin API for deleting the GoTrue identity on account erasure.
    gotrue_admin_url: str | None = None
    gotrue_service_role_key: str | None = None

    # --- database least privilege ---
    # Every app transaction runs `SET LOCAL ROLE <db_app_role>` so RLS binds even
    # when the connection user is the table owner/superuser (dev compose). In prod
    # point this at the dedicated login role (member of lexsim_app).
    db_app_role: str = "lexsim_app"
    # Fail closed if the effective role can bypass RLS (superuser/BYPASSRLS).
    db_require_non_superuser: bool = True

    # --- uploads (never served by the web app; outside the web root) ---
    storage_dir: str = "./storage"
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MB

    # Tests disable the limiter so Redis state from a previous run cannot make a
    # later run flaky; the limiter itself is unit-tested directly.
    rate_limit_enabled: bool = True

    # --- email (dev: Mailpit SMTP catch-all) ---
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "lexsim@localhost"

    # --- observability (optional; no DSN = no external sink) ---
    sentry_dsn: str | None = None

    # --- billing (Stripe test/prod; unset = 503 for real checkout) ---
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_automatic_tax: bool = True
    stripe_trial_days: int = 0
    checkout_success_url: str = "http://localhost:3000/?billing=success"
    checkout_cancel_url: str = "http://localhost:3000/?billing=cancel"

    # Browser origins allowed to call the API. JSON list in the environment,
    # e.g. CORS_ORIGINS='["https://app.example.com"]'.
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    environment: str = "dev"

    def validate_provider(self) -> None:
        """Fail fast at boot on misconfiguration (test_bedrock_region_pinned, S1)."""
        import re

        if self.db_app_role and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.db_app_role):
            raise ValidationError(
                f"DB_APP_ROLE must be a bare SQL identifier, got {self.db_app_role!r}"
            )
        if self.llm_provider not in ("ollama", "bedrock"):
            raise ValidationError(f"LLM_PROVIDER must be ollama|bedrock, got {self.llm_provider!r}")
        if self.llm_provider == "bedrock":
            if self.bedrock_region != "ap-southeast-2":
                raise ValidationError(
                    f"Bedrock region must be ap-southeast-2 (APP 8); got {self.bedrock_region!r}"
                )
            if self.bedrock_model not in ALLOWED_BEDROCK_MODEL_IDS:
                raise ValidationError(
                    f"Bedrock model {self.bedrock_model!r} not regional allow-listed "
                    "(no cross-region inference profiles — SECURITY_CHECKLIST S1/G8)"
                )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_provider()
    return settings
