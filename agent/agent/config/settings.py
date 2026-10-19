import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator, field_validator

# Load environment variables from .env file
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


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


def _find_project_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in [cur] + list(cur.parents):
        if (parent / "requirements.txt").exists() or (parent / "start_project.py").exists():
            return parent
    return cur.parents[3] if len(cur.parents) > 3 else cur.parent


class Settings(BaseModel):
    """Global settings for Agent Layer."""

    APP_NAME: str = os.getenv("APP_NAME", "Agent Layer")
    DEBUG: bool = _env_bool("DEBUG", True)
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = _env_int("PORT", 8000)
    RESEARCH_DEVELOPMENT_MODE: bool = _env_bool("RESEARCH_DEVELOPMENT_MODE", False)

    DEFAULT_RETRIEVAL_MODE: str = os.getenv("DEFAULT_RETRIEVAL_MODE", "hybrid")

    MIN_RETRIEVAL_SCORE: float = Field(
        default_factory=lambda: _env_float("MIN_RETRIEVAL_SCORE", 0.0),
        ge=0.0,
        le=1.0,
    )
    TOOL_TIMEOUT_MS: int = Field(
        default_factory=lambda: _env_int("TOOL_TIMEOUT_MS", 60000),
        gt=0,
    )
    TOOL_EXECUTOR_MAX_WORKERS: int = Field(
        default_factory=lambda: _env_int("TOOL_EXECUTOR_MAX_WORKERS", 8),
        ge=1,
    )
    TOOL_EXECUTOR_MAX_PENDING: int = Field(
        default_factory=lambda: _env_int("TOOL_EXECUTOR_MAX_PENDING", 16),
        ge=0,
    )
    RESEARCH_DATABASE_PATH: str = os.getenv(
        "RESEARCH_DATABASE_PATH",
        str(
            Path(__file__).resolve().parents[3]
            / "data-persistence"
            / "data"
            / "research_jobs.db"
        ),
    )
    RESEARCH_CHECKPOINT_PATH: str = os.getenv(
        "RESEARCH_CHECKPOINT_PATH",
        str(
            Path(__file__).resolve().parents[3]
            / "data-persistence"
            / "data"
            / "research_jobs.db.checkpoints"
        ),
    )
    RESEARCH_DOCUMENTS_DIR: str = os.getenv(
        "RESEARCH_DOCUMENTS_DIR",
        str(
            Path(__file__).resolve().parents[3]
            / "data-persistence"
            / "data"
            / "documents"
        ),
    )
    RESEARCH_DISPATCH_INTERVAL_SECONDS: float = Field(
        default_factory=lambda: _env_float(
            "RESEARCH_DISPATCH_INTERVAL_SECONDS",
            2.0,
        ),
        ge=0.25,
        le=60.0,
    )
    MEMORY_ENABLED: bool = _env_bool("MEMORY_ENABLED", True)
    MAX_MEMORY_MESSAGES: int = Field(
        default_factory=lambda: _env_int("MAX_MEMORY_MESSAGES", 10),
        ge=1,
    )
    PERSISTENT_MEMORY_ENABLED: bool = Field(default_factory=lambda: _env_bool("PERSISTENT_MEMORY_ENABLED", False))
    SESSION_FACT_ENABLED: bool = Field(default_factory=lambda: _env_bool("SESSION_FACT_ENABLED", False))
    MEMORY_CACHE_ENABLED: bool = Field(default_factory=lambda: _env_bool("MEMORY_CACHE_ENABLED", False))
    MEMORY_TAIL_MESSAGES: int = Field(
        default_factory=lambda: _env_int("MEMORY_TAIL_MESSAGES", 8),
        ge=1,
        le=100,
    )
    MEMORY_BRIEF_MAX_CHARS: int = Field(
        default_factory=lambda: _env_int("MEMORY_BRIEF_MAX_CHARS", 1200),
        ge=128,
        le=12000,
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
        ge=256,
        le=60000,
    )
    AGENT_INTERNAL_TOKEN: str = Field(default_factory=lambda: os.getenv("AGENT_INTERNAL_TOKEN", "").strip(), repr=False)
    MAX_REPEATED_TOOL_CALLS: int = Field(
        default_factory=lambda: _env_int("MAX_REPEATED_TOOL_CALLS", 2),
        ge=1,
    )

    THINKING_MAX_MODEL_CALLS: int = Field(default_factory=lambda: _env_int("THINKING_MAX_MODEL_CALLS", 10), ge=2, le=40)
    THINKING_MAX_TOOL_CALLS: int = Field(default_factory=lambda: _env_int("THINKING_MAX_TOOL_CALLS", 8), ge=1, le=30)
    THINKING_CONTEXT_MAX_CHARS: int = Field(default_factory=lambda: _env_int("THINKING_CONTEXT_MAX_CHARS", 30000), ge=6000, le=200000)
    THINKING_MAX_RESERVED_TOKENS: int = Field(default_factory=lambda: _env_int("THINKING_MAX_RESERVED_TOKENS", 150000), ge=1000)
    THINKING_MAX_VERIFICATIONS: int = Field(default_factory=lambda: _env_int("THINKING_MAX_VERIFICATIONS", 48), ge=1, le=300)
    THINKING_TIMEOUT_SECONDS: float = Field(default_factory=lambda: _env_float("THINKING_TIMEOUT_SECONDS", 180), gt=0, le=600)
    MINICHECK_MODEL_PATH: str = Field(default_factory=lambda: os.getenv("MINICHECK_MODEL_PATH", "data-persistence/models/minicheck"), validate_default=True)
    MINICHECK_CPU_THREADS: int = Field(default_factory=lambda: _env_int("MINICHECK_CPU_THREADS", 4), ge=1, le=32)

    LLM_API_KEY: str = Field(default_factory=lambda: os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", ""), repr=False)
    LLM_API_BASE: str = os.getenv(
        "LLM_API_BASE",
        os.getenv("OPENAI_API_BASE", "http://127.0.0.1:11434/v1"),
    )
    LLM_MODEL: str = os.getenv("LLM_MODEL", "llama3.1")
    ANSWER_FAST_MODEL: str = os.getenv("ANSWER_FAST_MODEL", "").strip()
    FAST_MODEL_SUPPORTS_IMAGES: bool = _env_bool("FAST_MODEL_SUPPORTS_IMAGES", False)
    FAST_CONTEXT_MAX_CHARS: int = Field(default_factory=lambda: _env_int("FAST_CONTEXT_MAX_CHARS", 12000), ge=1000, le=100000)
    ANSWER_FAST_MODEL_THINKING: bool = _env_bool(
        "ANSWER_FAST_MODEL_THINKING",
        False,
    )
    LLM_TEMPERATURE: float = _env_float("LLM_TEMPERATURE", 0.1)
    LLM_MAX_TOKENS: int = _env_int("LLM_MAX_TOKENS", 2000)
    LLM_TIMEOUT: int = _env_int("LLM_TIMEOUT", 60)
    LLM_THINKING_MODE: str = os.getenv("LLM_THINKING_MODE", "").strip().lower()
    LLM_REASONING_EFFORT: str = os.getenv("LLM_REASONING_EFFORT", "").strip().lower()
    RESEARCH_MODEL_REASONING_TOKENS: int = Field(default_factory=lambda: _env_int("RESEARCH_MODEL_REASONING_TOKENS", 3072), ge=0, le=32768)
    RESEARCH_MODEL_OUTPUT_TOKENS: int = Field(default_factory=lambda: _env_int("RESEARCH_MODEL_OUTPUT_TOKENS", 2048), ge=256, le=16384)
    RESEARCH_MODEL_TOTAL_TOKENS: int = Field(default_factory=lambda: _env_int("RESEARCH_MODEL_TOTAL_TOKENS", 64000), ge=1000, le=100000)
    RESEARCH_MODEL_MAX_RETRY_WAIT_SECONDS: float = Field(default_factory=lambda: _env_float("RESEARCH_MODEL_MAX_RETRY_WAIT_SECONDS", 60), ge=0, le=60)

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: Optional[str] = os.getenv("LOG_FILE")

    @field_validator("MINICHECK_MODEL_PATH", mode="before")
    @classmethod
    def resolve_minicheck_path(cls, value):
        path = Path(value or "data-persistence/models/minicheck").expanduser()
        return str(path if path.is_absolute() else _find_project_root() / path)

    @model_validator(mode="after")
    def reject_unsupported_memory_cache(self) -> "Settings":
        if self.MEMORY_CACHE_ENABLED:
            raise ValueError("memory_cache_not_supported")
        return self
    # Agent 服务共享密钥：Web 可信端调用 /api/* 业务接口时携带
    # `Authorization: Bearer <AGENT_API_KEY>`。未配置时 agent 业务接口
    # 返回 503，杜绝外部直连端口伪造 user_id 绕过权限隔离。
    AGENT_API_KEY: str = Field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""), repr=False)

    # 权限服务查询异常时的策略：
    # - False（默认，fail-closed）：返回空文档列表，拒绝全部文档访问，遵循最小权限。
    # - True（fail-open）：返回 None（不过滤），供排查/降级使用，需谨慎开启。
    PERMISSION_FAIL_OPEN: bool = _env_bool("PERMISSION_FAIL_OPEN", False)

    # Web 层 SQLite 数据库路径，Agent 层权限服务据此查询文件权限。
    # 默认定位到 AI-QA-Assistant/frontend/.data/sqlite.db。
    WEB_SQLITE_PATH: str = os.getenv(
        "WEB_SQLITE_PATH",
        str(_find_project_root() / "frontend" / ".data" / "sqlite.db"),
    )


settings = Settings()
