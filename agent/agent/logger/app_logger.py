# agent/logger/app_logger.py
import logging
import sys

# 避免循环导入，直接在这里定义 settings
from agent.config.settings import settings

# 配置基础日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout
)

logger = logging.getLogger("agent-layer")


def log_chat_result(trace_id: str, query: str, retrieval_count: int, status: str) -> None:
    logger.info(
        f"trace_id={trace_id} query={query} retrieval_count={retrieval_count} status={status}"
    )