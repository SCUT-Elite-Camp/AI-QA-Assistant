from typing import Any

from agent.prompt.templates import ANSWER_RULES, SYSTEM_ROLE


class PromptBuilder:
    def build(self, query: str, context: str = "") -> str:
        return f"""{SYSTEM_ROLE}

用户问题：
{query}

检索上下文：
{context}

严格约束：
{ANSWER_RULES}
"""
