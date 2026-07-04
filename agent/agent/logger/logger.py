# agent/logger/logger.py
import logging
import sys
from typing import Optional
from functools import wraps

from agent.trace.trace_id import get_trace_id
from agent.config.settings import settings


class TraceIdFilter(logging.Filter):
    """日志过滤器：自动注入 trace_id"""
    
    def filter(self, record):
        record.trace_id = get_trace_id() or "-"
        return True


def setup_logger(level: Optional[str] = None, log_file: Optional[str] = None) -> None:
    """
    配置全局日志
    
    Args:
        level: 日志级别，默认从 settings 读取
        log_file: 可选的日志文件路径
    """
    log_level = level or settings.LOG_LEVEL
    
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # 清除现有 handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.addFilter(TraceIdFilter())
    
    # 格式化器
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-7s | %(name)s | trace_id=%(trace_id)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 文件 handler（可选）
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.addFilter(TraceIdFilter())
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # 设置第三方库日志级别
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取 logger 实例"""
    return logging.getLogger(name)


def log_request(func):
    """装饰器：自动记录请求日志"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        logger.info(f"Calling {func.__name__}")
        try:
            result = func(*args, **kwargs)
            logger.info(f"{func.__name__} completed successfully")
            return result
        except Exception as e:
            logger.error(f"{func.__name__} failed: {str(e)}", exc_info=True)
            raise
    return wrapper