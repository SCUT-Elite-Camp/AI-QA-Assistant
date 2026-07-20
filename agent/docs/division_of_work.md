# 两人分工

## 成员 A：Agent 业务主流程负责人，也就是 xdj

负责：

- `agent/api/`
- `agent/service/`
- `agent/prompt/`
- `agent/llm/`
- `agent/formatter/`
- `agent/schemas/chat.py`
- `docs/interface_contract.md`

## 成员 B：Agent 基础设施负责人

负责：

- `agent/retrieval/`
- `agent/logger/`
- `agent/trace/`
- `agent/config/`
- `agent/errors/`
- `tests/`
- `agent/schemas/retrieval.py`

## 共同负责

- `agent/schemas/common.py`
- Web 联调
- Bug 修复
- Demo 问题集验证
- `docs/integration_record.md`

