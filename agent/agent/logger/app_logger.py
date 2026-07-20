# agent/logger/app_logger.py
import logging
import sys

# 避免循环导入，直接在这里定义 settings
from agent.config.settings import settings

from agent.logger.logger import get_logger

logger = get_logger("agent-layer")


def log_chat_result(
    trace_id: str,
    query: str,
    retrieval_count: int,
    status: str,
    stage: str = "completed",
    retrieval_mode: str = "",
    top_k: int | None = None,
    error: str = "",
) -> None:
    logger.info(
        "trace_id=%s stage=%s query=%s retrieval_mode=%s top_k=%s retrieval_count=%s status=%s error=%s",
        trace_id,
        stage,
        query,
        retrieval_mode,
        top_k,
        retrieval_count,
        status,
        error,
    )
