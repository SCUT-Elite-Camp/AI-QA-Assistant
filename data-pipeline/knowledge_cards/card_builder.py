"""批量知识卡片构建器 — P_s1

与 LightMem STM 设计一致:
- 一次 LLM 调用处理同一 topic 缓冲区中的多个段落
- 输出一组知识卡片（而非单张）
- 跨段事实自动合并（source_segments 标记多段来源）

中式 Prompt 适配：面向企业文档的知识提取场景。
"""

import json
import logging
import re
from typing import Optional

from segmenter.base import SemanticSegment
from knowledge_cards.schemas import KnowledgeCard

logger = logging.getLogger(__name__)

# ============================================================
# P_s1_batch Prompt 模板（中文）
# ============================================================

P_S1_BATCH_SYSTEM = (
    "你是企业文档知识卡片提取器。输出纯JSON，不要markdown代码块。"
)

P_S1_BATCH_USER = """你将看到同一话题下的一组文档段落（用 <!-- SEGMENT_N --> 标记段边界）。
请通读全部段落后，提取所有可辨识的独立知识点，每个知识点构造一张知识卡片。

话题: {topic}

输出纯JSON（不要markdown代码块），格式如下：
{{
  "topic_summary": "用1-2句话概括这批段落讨论的核心主题",
  "cards": [
    {{
      "key": "card:{{简短英文slug}}",
      "content": "原始文本中的关键事实（可跨段合并，保留原文措辞）",
      "source_segments": [0, 1],
      "keywords": ["关键词1", "关键词2"],
      "tags": ["fact", "data_point"],
      "description": "一句话概括本条知识",
      "confidence": 0.9
    }}
  ]
}}

规则：
1. 努力识别所有独立知识点，通常3-10张卡片/批次
2. 如果一个事实跨越多段（如"净利润120亿"在段0，"同比增长23%"在段1），合并为一张卡片，source_segments标记[0,1]
3. content 只包含原文中明确陈述的事实，不得推断
4. keywords 每张卡片提取3-5个最核心的检索关键词
5. tags 从以下类型中选择：fact(事实), decision(决策), constraint(约束), event(事件), definition(定义), process(流程), data_point(数据点)
6. description 用一句话总结该知识要点
7. 过渡句、目录、免责声明等不要提取为卡片
8. 如果某个段落没有可提取的知识，简单跳过
9. 如果整批都没有可提取的知识，返回空的 cards 列表

文档段落：
{context_text}"""


class CardConstructor:
    """批量知识卡片构建器

    变化：旧方案 build_card(segment_text) → 一段调一次LLM → 一张卡
          新方案 build_cards_batch(segments[], context_text, topic) → 一批调一次LLM → 一组卡

    为什么更好：
    - LLM 看到完整段落群上下文，理解主题后再提取
    - 跨段事实自动合并（source_segments 标记多段来源）
    - 过渡句/目录/免责声明在上下文中自然识别为噪声
    - API 调用次数 5-10x 减少
    """

    def __init__(
        self,
        llm_base_url: str = "http://127.0.0.1:11434/v1",
        llm_model: str = "llama3.1",
        llm_temperature: float = 0.1,
        llm_max_tokens: int = 2048,
        llm_api_key: str = "",
        llm_timeout: int = 120,
    ):
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.llm_temperature = llm_temperature
        self.llm_max_tokens = llm_max_tokens
        self.llm_api_key = llm_api_key
        self.llm_timeout = llm_timeout

        # 统计
        self.total_calls = 0
        self.total_cards_generated = 0

    def build_cards_batch(
        self,
        segments: list[SemanticSegment],
        context_text: str,
        topic: str = "通用",
    ) -> list[KnowledgeCard]:
        """从一批语义段落中提取一组知识卡片

        Args:
            segments: 同一 topic 的语义段落列表
            context_text: 拼接好的上下文文本（含 SEGMENT_N 标记）
            topic: 话题名（topic_id 或 topic_summary）

        Returns:
            提取的知识卡片列表
        """
        if not segments or not context_text.strip():
            return []

        prompt = P_S1_BATCH_USER.format(
            topic=topic,
            context_text=context_text,
        )

        raw_response = self._call_llm(
            system=P_S1_BATCH_SYSTEM,
            user_prompt=prompt,
        )

        cards = self._parse_response(raw_response, segments)
        self.total_cards_generated += len(cards)
        return cards

    def _call_llm(self, system: str, user_prompt: str) -> str:
        """调用 OpenAI-compatible LLM（Ollama 默认为主）

        复用与现有 agent/llm/llm_client.py 相同的接口约定。
        """
        import urllib.request
        import urllib.error

        url = f"{self.llm_base_url.rstrip('/')}/chat/completions"

        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.llm_temperature,
            "max_tokens": self.llm_max_tokens,
            "response_format": {"type": "json_object"},  # Ollama 支持
        }

        headers = {"Content-Type": "application/json"}
        if self.llm_api_key:
            headers["Authorization"] = f"Bearer {self.llm_api_key}"

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=self.llm_timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                self.total_calls += 1
                content = body["choices"][0]["message"]["content"]
                return content
        except urllib.error.URLError as e:
            logger.error(f"LLM call failed: {e}")
            return "{}"
        except Exception as e:
            logger.error(f"LLM call error: {e}")
            return "{}"

    def _parse_response(
        self,
        raw_response: str,
        segments: list[SemanticSegment],
    ) -> list[KnowledgeCard]:
        """解析 LLM 返回的 JSON 响应为 KnowledgeCard 列表"""
        if not raw_response or raw_response.strip() == "{}":
            return []

        # 尝试提取 JSON（有些模型会在 JSON 外包 markdown 代码块）
        json_str = raw_response.strip()
        if json_str.startswith("```"):
            json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
            json_str = re.sub(r"\s*```$", "", json_str)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}")
            logger.debug(f"Raw response (first 500 chars): {raw_response[:500]}")
            return []

        cards_raw = data.get("cards", [])
        if not cards_raw:
            return []

        cards = []
        doc_id = segments[0].doc_id if segments else ""

        for item in cards_raw:
            if not item.get("content"):
                continue

            # 解析 source_segments → 映射到实际的 segment_id
            source_indices = item.get("source_segments", [0])
            if isinstance(source_indices, int):
                source_indices = [source_indices]

            source_ids = []
            for idx in source_indices:
                if isinstance(idx, int) and 0 <= idx < len(segments):
                    source_ids.append(segments[idx].segment_id)

            # 如果未指定 source_segments，默认用第一个段
            if not source_ids and segments:
                source_ids = [segments[0].segment_id]

            card = KnowledgeCard(
                content=item.get("content", ""),
                keywords=item.get("keywords", []),
                tags=item.get("tags", []),
                context=item.get("description", ""),
                source_segments=source_ids,
                doc_id=doc_id,
            )

            cards.append(card)

        return cards
