"""Application settings via pydantic-settings.

Environment variables are documented in ``backend/.env.example`` and mirror
the fields on :class:`Settings`.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend settings loaded from environment / .env file.

    API secrets (``DART_API_KEY`` and ``LLM_API_KEY``) use ``SecretStr`` and
    must never be logged.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DART (OpenDART) -- secret; keep as SecretStr, never log its value.
    dart_api_key: SecretStr | None = None
    dart_base_url: str = "https://opendart.fss.or.kr/api"

    # LLM provider (Groq by default, D68) -- OpenAI-compatible chat completions. The LLM writes only
    # narrative (numbers come from the structured filing API); this is the one
    # provider seam (see app.llm). llm_api_key is a secret -- never log it; it
    # travels only in the Authorization header. base_url is the OpenAI-compatible
    # root (adapter appends /chat/completions); model is configurable -- the exact
    # model name may change independently of this default.
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "qwen/qwen3.8-27b"

    # SEC EDGAR -- requires a User-Agent with contact info (name + email).
    sec_base_url: str = "https://data.sec.gov"
    sec_user_agent: str = "filing-footnote/0.5.2 your-contact@example.com"

    database_url: str = (
        "postgresql+psycopg://filing_footnote:filing_footnote_dev@localhost:5433/filing_footnote"
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (one read per process)."""
    return Settings()
