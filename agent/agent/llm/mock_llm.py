from agent.llm.base import BaseLLM


class MockLLM(BaseLLM):
    def __init__(self, should_raise: bool = False) -> None:
        self.should_raise = should_raise

    def generate(self, prompt: str) -> str:
        if self.should_raise:
            raise RuntimeError("mock llm error")

        # Parse the prompt to extract user question and context
        query = ""
        context = ""

        try:
            parts = prompt.split("用户问题：")
            if len(parts) > 1:
                subparts = parts[1].split("检索上下文：")
                query = subparts[0].strip()
                if len(subparts) > 1:
                    context = subparts[1].split("严格约束：")[0].strip()
        except Exception:
            pass

        if not context:
            return f"未能检索到相关上下文回答您关于 '{query}' 的提问。"

        # Parse context block-by-block
        blocks = context.split("\n\n")
        chunks = []
        for block in blocks:
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            if not lines:
                continue
            idx = ""
            title = ""
            doc_id = ""
            chunk_id = ""
            content = ""
            for line in lines:
                if line.startswith("[") and line.endswith("]"):
                    idx = line[1:-1]
                elif "title" in line:
                    title = line.split("title")[-1].lstrip("=: ")
                elif "doc_id" in line:
                    doc_id = line.split("doc_id")[-1].lstrip("=: ")
                elif "chunk_id" in line:
                    chunk_id = line.split("chunk_id")[-1].lstrip("=: ")
                elif "chunk_text" in line:
                    content = line.split("chunk_text")[-1].lstrip("=: ")
                elif "content" in line:
                    content = line.split("content")[-1].lstrip("=: ")
            if idx and content:
                chunks.append((idx, title, doc_id, chunk_id, content))

        if not chunks:
            return f"针对您提出的问题「**{query}**」，系统已检索到内容但未能成功解析结构化文本。"

        # Construct a beautiful, dynamic answer using the retrieved chunks
        answer_parts = []
        answer_parts.append(f"针对您提出的问题「**{query}**」，检索匹配到以下内容：\n\n")

        for idx, title, doc_id, chunk_id, content in chunks:
            title_clean = title.strip() or "未命名文档"
            content_clean = content.strip()
            # Truncate content for a cleaner presentation if necessary
            if len(content_clean) > 200:
                content_clean = content_clean[:200] + "..."
            answer_parts.append(f"- **来自文档《{title_clean}》**：{content_clean} [{idx}]\n")

        answer_parts.append("\n（以上答案由 RAG 向量检索并在 Mock LLM 调试模式下根据匹配片段动态组装生成。）")
        return "".join(answer_parts)
