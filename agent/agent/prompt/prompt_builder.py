from typing import Any

from agent.prompt.templates import ANSWER_RULES, SYSTEM_ROLE


class PromptBuilder:
    def build(
        self,
        query: str,
        chunks: list[Any] | None = None,
        context: str | None = None,
    ) -> str:
        context_text = self._build_context(chunks or []) if chunks is not None else (context or "")
        return f"""{SYSTEM_ROLE}

用户问题：
{query}

检索上下文：
{context_text}

严格约束：
{ANSWER_RULES}
"""

    def _build_context(self, chunks: list[Any]) -> str:
        blocks = []
        for index, chunk in enumerate(chunks, start=1):
            blocks.append(
                "\n".join(
                    [
                        f"[{index}] title={self._read(chunk, 'title', '')}",
                        f"doc_id={self._read(chunk, 'doc_id', '')}",
                        f"chunk_id={self._read(chunk, 'chunk_id', '')}",
                        f"content={self._read(chunk, 'chunk_text', '')}",
                    ]
                )
            )
        return "\n\n".join(blocks)

    def _read(self, chunk: Any, field: str, default: Any = None) -> Any:
        if isinstance(chunk, dict):
            return chunk.get(field, default)
        return getattr(chunk, field, default)
