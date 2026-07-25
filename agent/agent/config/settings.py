import os
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load environment variables from .env file
load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


class Settings(BaseModel):
    """Global settings for Agent Layer."""

    APP_NAME: str = os.getenv("APP_NAME", "Agent Layer")
    DEBUG: bool = _env_bool("DEBUG", True)
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = _env_int("PORT", 8000)

    DEFAULT_TOP_K: int = Field(default_factory=lambda: _env_int("DEFAULT_TOP_K", 5), ge=1, le=20)
    MIN_RETRIEVAL_SCORE: float = Field(
        default_factory=lambda: _env_float("MIN_RETRIEVAL_SCORE", 0.0),
        ge=0.0,
        le=1.0,
    )
    DEFAULT_RETRIEVAL_MODE: str = os.getenv("DEFAULT_RETRIEVAL_MODE", "hybrid")
    QUERY_UNDERSTANDING_ENABLED: bool = _env_bool(
        "QUERY_UNDERSTANDING_ENABLED",
        True,
    )
    QUERY_REWRITE_ENABLED: bool = _env_bool("QUERY_REWRITE_ENABLED", True)
    CLARIFICATION_ENABLED: bool = _env_bool("CLARIFICATION_ENABLED", True)

    LLM_API_KEY: str = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    LLM_API_BASE: str = os.getenv(
        "LLM_API_BASE",
        os.getenv("OPENAI_API_BASE", "http://127.0.0.1:11434/v1"),
    )
    LLM_MODEL: str = os.getenv("LLM_MODEL", "llama3.1")
    LLM_TEMPERATURE: float = _env_float("LLM_TEMPERATURE", 0.1)
    LLM_MAX_TOKENS: int = _env_int("LLM_MAX_TOKENS", 2000)
    LLM_TIMEOUT: int = _env_int("LLM_TIMEOUT", 60)

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: Optional[str] = os.getenv("LOG_FILE")


settings = Settings()
