import os
from typing import Optional

from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field

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
    UNIFIED_QUERY_UNDERSTANDING_ENABLED: bool = _env_bool(
        "UNIFIED_QUERY_UNDERSTANDING_ENABLED",
        False,
    )
    CASCADED_QUERY_UNDERSTANDING_ENABLED: bool = _env_bool(
        "CASCADED_QUERY_UNDERSTANDING_ENABLED",
        False,
    )
    HYBRID_INTENT_ROUTER_ENABLED: bool = _env_bool(
        "HYBRID_INTENT_ROUTER_ENABLED",
        False,
    )
    INTENT_EMBEDDING_MODEL_PATH: str = os.getenv(
        "INTENT_EMBEDDING_MODEL_PATH",
        "",
    )
    INTENT_EMBEDDING_THRESHOLD: float = Field(
        default_factory=lambda: _env_float("INTENT_EMBEDDING_THRESHOLD", 0.72),
        ge=-1.0,
        le=1.0,
    )
    INTENT_EMBEDDING_MARGIN: float = Field(
        default_factory=lambda: _env_float("INTENT_EMBEDDING_MARGIN", 0.08),
        ge=0.0,
        le=2.0,
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
    QUERY_PREPARATION_MODEL: str = os.getenv("QUERY_PREPARATION_MODEL", "").strip()
    ANSWER_COMPLETENESS_MODEL: str = os.getenv("ANSWER_COMPLETENESS_MODEL", "").strip()
    ANSWER_COMPLETENESS_MODEL_THINKING: bool = _env_bool(
        "ANSWER_COMPLETENESS_MODEL_THINKING",
        False,
    )
    ANSWER_FAST_MODEL: str = os.getenv("ANSWER_FAST_MODEL", "").strip()
    ANSWER_FAST_MODEL_THINKING: bool = _env_bool(
        "ANSWER_FAST_MODEL_THINKING",
        False,
    )
    LLM_TEMPERATURE: float = _env_float("LLM_TEMPERATURE", 0.1)
    LLM_MAX_TOKENS: int = _env_int("LLM_MAX_TOKENS", 2000)
    LLM_TIMEOUT: int = _env_int("LLM_TIMEOUT", 60)

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: Optional[str] = os.getenv("LOG_FILE")


settings = Settings()
