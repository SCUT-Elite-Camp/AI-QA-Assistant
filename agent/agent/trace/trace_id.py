"""
Trace ID 生成和管理模块
"""
import uuid
import time
from contextvars import ContextVar
from typing import Optional

# 当前请求的 trace_id（支持异步）
_current_trace_id: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


def generate_trace_id() -> str:
    """
    生成唯一 trace_id
    
    格式: trace-{uuid前8位}-{timestamp后6位}
    示例: trace-a1b2c3d4-123456
    """
    uuid_part = uuid.uuid4().hex[:8]
    timestamp_part = str(int(time.time() * 1000))[-6:]
    return f"trace-{uuid_part}-{timestamp_part}"


def set_trace_id(trace_id: str) -> None:
    """设置当前请求的 trace_id"""
    _current_trace_id.set(trace_id)


def get_trace_id() -> Optional[str]:
    """获取当前请求的 trace_id"""
    return _current_trace_id.get()


def clear_trace_id() -> None:
    """清除当前请求的 trace_id"""
    _current_trace_id.set(None)
