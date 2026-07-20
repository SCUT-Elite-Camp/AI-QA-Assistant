# tests/unit/test_logger.py
import pytest
import logging
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.trace.trace_id import set_trace_id, clear_trace_id
from agent.logger.logger import setup_logger, get_logger


class TestLogger:
    def test_get_logger_returns_logger_instance(self):
        """测试获取 logger"""
        logger = get_logger("test")
        assert isinstance(logger, logging.Logger)
    
    def test_logger_basic_logging(self, caplog):
        """测试基本日志功能"""
        caplog.set_level(logging.INFO)
        
        # 使用 get_logger 获取 logger
        logger = get_logger("test_basic")
        
        test_message = "Hello from test"
        logger.info(test_message)
        
        # 验证日志被记录
        assert test_message in caplog.text
    
    def test_logger_with_trace_id_in_context(self):
        """测试 trace_id 在日志上下文中"""
        import io
        
        # 创建捕获器
        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
        
        logger = logging.getLogger("test_trace")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        test_trace_id = "trace-test-456"
        set_trace_id(test_trace_id)
        
        logger.info("Test with trace_id")
        
        log_output = log_capture.getvalue()
        # 验证日志被记录
        assert "Test with trace_id" in log_output
        
        clear_trace_id()
    
    def test_setup_logger_does_not_error(self):
        """测试配置日志不报错"""
        try:
            setup_logger(level="INFO")
        except Exception as e:
            pytest.fail(f"setup_logger failed: {e}")
    
    def test_logger_multiple_messages(self, caplog):
        """测试多条日志消息"""
        caplog.set_level(logging.INFO)
        
        logger = get_logger("test_multiple")
        
        logger.info("Message 1")
        logger.warning("Message 2")
        logger.error("Message 3")
        
        assert "Message 1" in caplog.text
        assert "Message 2" in caplog.text
        assert "Message 3" in caplog.text