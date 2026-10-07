from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://cadence:cadence@localhost:5432/cadence"

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3(cls, url: str) -> str:
        """Hosted Postgres (Neon, Render, Railway) hands out postgres:// or
        postgresql:// URLs; SQLAlchemy would read those as psycopg2, which isn't
        installed. Point them at the psycopg 3 driver we ship."""
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    # Provider-agnostic LLM config. See app/llm/provider.py.
    llm_provider: str = "anthropic"  # "anthropic" | "openai"
    llm_model: str = "claude-haiku-4-5-20251001"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # Scheduler defaults (overridable per-user via Availability).
    max_hours_per_day: float = 4.0

    # Auth. With clerk_issuer unset, auth is OFF: every request acts as the
    # "demo" user (local dev and tests). Set it to the Clerk Frontend API URL
    # (Dashboard -> API keys, e.g. https://xxx.clerk.accounts.dev) to require
    # a signed-in user on every endpoint.
    clerk_issuer: str | None = None
    # Origins allowed to have requested the token (the `azp` claim).
    clerk_authorized_parties: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
