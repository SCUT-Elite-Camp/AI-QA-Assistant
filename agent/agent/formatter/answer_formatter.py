import re

from agent.schemas.chat import ChatResponse, Citation
from agent.schemas.common import StatusCode
from agent.schemas.retrieval import RetrievalResult

# 传统引用格式: [1], [2], [3]
_LEGACY_REF_PATTERN = re.compile(r"\[(\d+)\]")

# Agentic 引用格式: [K-1], [K-2], [S-1], [S-2]
_AGENTIC_REF_PATTERN = re.compile(r"\[([KS])-(\d+)\]")

# 组合：匹配所有引用格式
_ALL_REFS_PATTERN = re.compile(r"\[(\d+)\]|\[([KS])-(\d+)\]")


class AnswerFormatter:
    """答案格式化器，负责引用规范化。

    支持两种引用格式:
    - [N]: 传统连续编号（legacy）
    - [K-N] / [S-N]: agentic 知识卡片/段落引用
    """

    def format_success(
        self,
        trace_id: str,
        answer: str,
        retrieval_results: list[RetrievalResult],
    ) -> ChatResponse:
        citations = [
            Citation(
                citation_id=index,
                title=result.title,
                source_url=result.source_url,
                doc_id=result.doc_id,
                chunk_id=result.chunk_id,
                score=result.score,
                snippet=result.chunk_text,
            )
            for index, result in enumerate(retrieval_results, start=1)
        ]
        safe_answer = self._normalize_answer_references(
            answer.strip(),
            len(citations),
            retrieval_results,
        )
        return ChatResponse(
            trace_id=trace_id,
            status=StatusCode.SUCCESS,
            answer=safe_answer,
            message="",
            citations=citations,
        )

    def _normalize_answer_references(
        self,
        answer: str,
        citations_count: int,
        retrieval_results: list[RetrievalResult] | None = None,
    ) -> str:
        """规范化答案中的引用标记。

        保留有效的 [N]、[K-N]、[S-N] 引用，
        清除无效（越界）的引用编号。
        如果没有有效引用，自动追加 [1]。
        """
        if not answer or citations_count == 0:
            return answer

        # 检测是否使用 agentic 引用格式
        has_agentic_refs = bool(_AGENTIC_REF_PATTERN.search(answer))

        if has_agentic_refs:
            return self._normalize_agentic_references(
                answer,
                retrieval_results or [],
            )
        else:
            return self._normalize_legacy_references(answer, citations_count)

    def _normalize_legacy_references(
        self,
        answer: str,
        citations_count: int,
    ) -> str:
        """规范化传统 [N] 引用格式"""
        valid_ids = {str(index) for index in range(1, citations_count + 1)}
        has_valid_reference = False

        def replace_ref(match: re.Match[str]) -> str:
            nonlocal has_valid_reference
            citation_id = match.group(1)
            if citation_id in valid_ids:
                has_valid_reference = True
                return match.group(0)
            return ""

        normalized = _LEGACY_REF_PATTERN.sub(replace_ref, answer)
        normalized = re.sub(r"\s{2,}", " ", normalized).strip()

        if not has_valid_reference:
            normalized = f"{normalized} [1]".strip()

        return normalized

    def _normalize_agentic_references(
        self,
        answer: str,
        retrieval_results: list[RetrievalResult],
    ) -> str:
        """规范化 agentic [K-N] / [S-N] 引用格式。

        验证规则:
        - K 引用必须对应 source_type == "card" 的结果
        - S 引用必须对应 source_type == "segment" (或非 card) 的结果
        - 编号必须在有效范围内
        """
        # 建立引用映射: "K-1" → result index
        card_count = 0
        segment_count = 0
        card_index_map: dict[int, int] = {}   # K-N → global citation index
        segment_index_map: dict[int, int] = {} # S-N → global citation index

        for idx, r in enumerate(retrieval_results):
            source_type = (getattr(r, "source_type", None) or "").lower()
            if source_type == "card":
                card_count += 1
                card_index_map[card_count] = idx + 1  # 1-based citation
            else:
                segment_count += 1
                segment_index_map[segment_count] = idx + 1

        has_valid_reference = False

        def replace_ref(match: re.Match[str]) -> str:
            nonlocal has_valid_reference
            prefix = match.group(2) or match.group(1)
            num_str = match.group(3) or match.group(1)
            num = int(num_str)

            if prefix == "K" and num in card_index_map:
                has_valid_reference = True
                return f"[K-{num}]"
            elif prefix == "S" and num in segment_index_map:
                has_valid_reference = True
                return f"[S-{num}]"
            elif prefix.isdigit() and 1 <= num <= len(retrieval_results):
                has_valid_reference = True
                return f"[{num}]"
            return ""

        normalized = _ALL_REFS_PATTERN.sub(replace_ref, answer)
        normalized = re.sub(r"\s{2,}", " ", normalized).strip()

        if not has_valid_reference and len(retrieval_results) > 0:
            normalized = f"{normalized} [1]".strip()

        return normalized
