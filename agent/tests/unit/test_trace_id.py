from agent.trace.trace_id import (
    generate_trace_id,
    set_trace_id,
    get_trace_id,
    clear_trace_id,
)


class TestTraceId:
    def test_generate_trace_id_format(self):
        """测试 trace_id 格式"""
        trace_id = generate_trace_id()
        assert trace_id.startswith("trace-")
        assert len(trace_id) > 10
    
    def test_generate_trace_id_unique(self):
        """测试 trace_id 唯一性"""
        ids = [generate_trace_id() for _ in range(100)]
        assert len(set(ids)) == 100
    
    def test_set_and_get_trace_id(self):
        """测试设置和获取 trace_id"""
        test_id = "test-123"
        set_trace_id(test_id)
        assert get_trace_id() == test_id
        clear_trace_id()
        assert get_trace_id() is None
