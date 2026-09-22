from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://cadence:cadence@localhost:5432/cadence"

    # Provider-agnostic LLM config. See app/llm/provider.py.
    llm_provider: str = "anthropic"  # "anthropic" | "openai"
    llm_model: str = "claude-haiku-4-5-20251001"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # Scheduler defaults (overridable per-user via Availability).
    max_hours_per_day: float = 4.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
