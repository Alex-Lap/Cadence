"""Single place where a chat model is constructed.

Everything else in the app depends on this function, not on a vendor SDK, so
swapping providers is a config change.
"""

from typing import Any

from app.config import get_settings


def get_chat_model(**overrides: Any):
    s = get_settings()
    provider = overrides.pop("provider", s.llm_provider)
    model = overrides.pop("model", s.llm_model)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model, api_key=s.anthropic_api_key, **overrides)

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, api_key=s.openai_api_key, **overrides)

    raise ValueError(f"Unknown llm_provider: {provider!r}")
