import os
from typing import Optional

from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

# Load environment variables from agent/.env and root .env
_agent_env = Path(__file__).resolve().parent.parent.parent / ".env"
if _agent_env.exists():
    load_dotenv(_agent_env)
_root_env = Path(__file__).resolve().parent.parent.parent.parent / ".env"
if _root_env.exists():
    load_dotenv(_root_env)
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
    TOOL_TIMEOUT_MS: int = Field(
        default_factory=lambda: _env_int("TOOL_TIMEOUT_MS", 60000),
        gt=0,
    )


    MEMORY_ENABLED: bool = _env_bool("MEMORY_ENABLED", True)
    MAX_MEMORY_MESSAGES: int = Field(
        default_factory=lambda: _env_int("MAX_MEMORY_MESSAGES", 10),
        ge=1,
    )
    # Persistent Memory is separately gated and remains disabled until rollout.
    PERSISTENT_MEMORY_ENABLED: bool = Field(
        default_factory=lambda: _env_bool("PERSISTENT_MEMORY_ENABLED", False),
    )
    SESSION_FACT_ENABLED: bool = Field(
        default_factory=lambda: _env_bool("SESSION_FACT_ENABLED", False),
    )
    MEMORY_CACHE_ENABLED: bool = Field(
        default_factory=lambda: _env_bool("MEMORY_CACHE_ENABLED", False),
    )
    MEMORY_TAIL_MESSAGES: int = Field(
        default_factory=lambda: _env_int("MEMORY_TAIL_MESSAGES", 8),
        ge=1,
    )
    MEMORY_BRIEF_MAX_CHARS: int = Field(
        default_factory=lambda: _env_int("MEMORY_BRIEF_MAX_CHARS", 1200),
        ge=1,
    )
    MEMORY_SNAPSHOT_SUMMARY_MAX_CHARS: int = Field(
        default_factory=lambda: _env_int("MEMORY_SNAPSHOT_SUMMARY_MAX_CHARS", 1200),
        ge=1,
    )
    MEMORY_COMPACTION_MIN_MESSAGES: int = Field(
        default_factory=lambda: _env_int("MEMORY_COMPACTION_MIN_MESSAGES", 12),
        ge=1,
    )
    MEMORY_COMPACTION_SOFT_TOKENS: int = Field(
        default_factory=lambda: _env_int("MEMORY_COMPACTION_SOFT_TOKENS", 1000),
        ge=1,
    )
    MEMORY_MODEL_HISTORY_MAX_CHARS: int = Field(
        default_factory=lambda: _env_int("MEMORY_MODEL_HISTORY_MAX_CHARS", 6000),
        ge=1,
    )
    # Empty by default; 04a rejects private requests unless the configured token matches.
    AGENT_INTERNAL_TOKEN: str = Field(
        default_factory=lambda: os.getenv("AGENT_INTERNAL_TOKEN", ""),
    )
    MAX_AGENT_ITERATIONS: int = Field(
        default_factory=lambda: _env_int("MAX_AGENT_ITERATIONS", 5),
        ge=1,
    )
    MAX_REPEATED_TOOL_CALLS: int = Field(
        default_factory=lambda: _env_int("MAX_REPEATED_TOOL_CALLS", 2),
        ge=1,
    )

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

    @model_validator(mode="after")
    def reject_unsupported_memory_cache(self) -> "Settings":
        if self.MEMORY_CACHE_ENABLED:
            raise ValueError("memory_cache_not_supported")
        return self


settings = Settings()
