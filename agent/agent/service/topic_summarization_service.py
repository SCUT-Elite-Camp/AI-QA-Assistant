import json
from typing import List, Dict, Any, Optional
from agent.llm.base import BaseLLM
from data_persistence.topics import TopicArtifactRepository
from agent.service.access_guard import check_model_access, CURRENT_ACCESS_GUARD
from agent.service.permission_service import PermissionResolutionError


class TopicSummarizationService:
    """
    Agent application service:
    Executes a single structured LLM request to extract discussion content and reference existing topic state,
    generating Title, Description, System Core Cognition (Soul.md), and Content Tags.
    Delegates topic artifact storage to the persistence repository.
    """

    def __init__(self, llm: BaseLLM, repository: TopicArtifactRepository) -> None:
        self.llm = llm
        self.repository = repository

    def _call_llm(self, messages: List[Dict[str, str]], max_tokens: int = 2500, temperature: float = 0.2) -> str:
        """Return model text while keeping transport and configuration in Agent."""
        try:
            check_model_access()
            message = self.llm.chat(messages, max_tokens=max_tokens, temperature=temperature) or {}
            check_model_access()
            content = (message.get("content") or "").strip()
            if content:
                return content
            return (message.get("reasoning_content") or "").strip()
        except PermissionResolutionError:
            raise
        except Exception:
            return ""

    def summarize_and_persist(
        self,
        topic_id: str,
        discussion_text: str,
        custom_title: Optional[str] = None,
        existing_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        repository = self.repository

        if custom_title and (custom_title.startswith("我想知道") or custom_title.startswith("请问") or custom_title == "新对话"):
            custom_title = None

        # Read existing topic state or preserve the caller-supplied state.
        # Guarded HTTP requests may use only server-verified state, not a disk
        # fallback without provenance. Direct component callers retain their API.
        existing_info = (existing_info or {}) if CURRENT_ACCESS_GUARD.get() else repository.load_existing(topic_id, existing_info)

        # Truncate discussion text to prevent context window overflow (~6000 chars max)
        MAX_DISCUSSION_CHARS = 6000
        if len(discussion_text) > MAX_DISCUSSION_CHARS:
            # Keep first and last parts for context
            half = MAX_DISCUSSION_CHARS // 2
            discussion_text = discussion_text[:half] + "\n\n...[中间内容省略]...\n\n" + discussion_text[-half:]

        # 2. Build Single Prompt with Conversation + Existing Metadata reference
        existing_title = existing_info.get("title", "")
        existing_desc = existing_info.get("description", "")
        existing_soul = existing_info.get("soulContent", "")
        existing_tags = existing_info.get("tags", [])

        ref_block = ""
        if existing_title or existing_soul or existing_desc:
            ref_block = f"""
历史已有话题信息（供对比参考与增量演进）：
- 历史标题: {existing_title or '无'}
- 历史描述: {existing_desc or '无'}
- 历史标签: {json.dumps(existing_tags, ensure_ascii=False) if existing_tags else '无'}
- 历史系统指示/认知:
{existing_soul or '无'}
"""

        title_instruction = f"用户已指定标题为「{custom_title.strip()}」，请保持 title 为此标题。" if custom_title and custom_title.strip() else "请根据对话精炼生成 3-10 字极简专业标题（如 'Toolset 架构与接口'），绝对不要包含聊天动词（如'我想知道'、'怎么做'）和标点。"

        system_prompt = """你是一个高级知识工程与技术场景分析专家。你的任务是根据话题讨论内容，生成该话题的完整元数据（标题、描述、认知文档、标签）。

要求：
1. 标题必须精简专业（3-10字），绝不要包含"我想知道"、"请问"、"怎么做"等聊天动词或标点符号
2. 描述用一句话精炼概括核心用途与适用场景（40-60字），独立撰写，禁止直接复制指示内容
3. soul_content 是 Markdown 格式的系统认知文档，按给定的结构填写
4. 标签提取 2-4 个精准关键词
5. 如果已有历史话题信息，结合历史信息进行增量演进，但不要被低质量的历史标题带偏

请严格输出合法的 JSON 对象格式（不要包含任何 JSON 之外的聊天解释或文本）。"""

        user_prompt = f"""最新讨论内容：
{discussion_text}
{ref_block}
{title_instruction}

请严格输出合法的 JSON 对象格式：
```json
{{
  "title": "3-10字极简专业标题",
  "description": "一句话精炼概括核心用途与适用场景（40-60字）",
  "soul_content": "# 话题认知: [标题]\\n## 核心实体与领域\\n- [提取2-4个关键实体/术语]\\n## 场景边界与目标\\n- **核心目标**: [核心研究目标]\\n- **适用边界**: [边界与不包含范围]\\n## 关键背景摘要\\n- [核心背景要点]",
  "tags": ["标签1", "标签2", "标签3"]
}}
```"""

        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]

        # Retry up to 2 times on empty response
        raw_resp = ""
        for attempt in range(2):
            raw_resp = self._call_llm(messages, max_tokens=2500, temperature=0.2)
            if raw_resp and raw_resp.strip():
                break
            print(f"[TopicSummarizationService] Warning: LLM returned empty response on attempt {attempt + 1}, retrying...")
        
        parsed = self._parse_and_verify_json(raw_resp, custom_title, discussion_text, existing_info)

        title = parsed["title"]
        description = parsed["description"]
        soul_content = parsed["soul_content"]
        tags = parsed["tags"]

        check_model_access()
        persisted = repository.save_summary(
            topic_id,
            title=title,
            description=description,
            soul_content=soul_content,
            tags=tags,
            existing_info=existing_info,
        )
        return {
            "title": persisted["title"],
            "description": persisted.get("description"),
            "soul_content": persisted.get("soulContent", ""),
            "tags": persisted.get("tags") or [],
        }


    @staticmethod
    def _clean_title(raw: str) -> str:
        if not raw:
            return ""
        s = raw.strip()
        for prefix in ["问:", "问：", "问: ", "问： ", "答:", "答：", "我想知道", "请问", "关于", "怎么做"]:
            if s.startswith(prefix):
                s = s[len(prefix):].strip()
        return s.replace("！", "").replace("。", "").strip()

    @staticmethod
    def _parse_and_verify_json(
        raw_resp: str,
        custom_title: Optional[str],
        discussion_text: str,
        existing_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Strictly extracts, parses, and validates JSON object returned by LLM."""
        if not raw_resp:
            return TopicSummarizationService._fallback(custom_title, discussion_text, existing_info)

        import re
        data = None

        text = raw_resp.strip()
        # 1. Try finding ```json { ... } ``` regex match
        json_match = re.search(r"```json\s*(\{.*\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
            except Exception:
                pass

        # 2. Try slice from first '{' to last '}'
        if not data:
            start_idx = text.find("{")
            end_idx = text.rfind("}")
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                candidate = text[start_idx:end_idx+1]
                try:
                    data = json.loads(candidate)
                except Exception:
                    try:
                        sanitized = re.sub(r'"([^"\\]|\\.)*"', lambda m: m.group(0).replace('\n', '\\n').replace('\r', '\\r'), candidate, flags=re.DOTALL)
                        data = json.loads(sanitized)
                    except Exception as e:
                        print(f"[TopicSummarizationService] JSON parse verification failed: {e}")

        if not data or not isinstance(data, dict):
            return TopicSummarizationService._fallback(custom_title, discussion_text, existing_info)

        raw_title = str(data.get("title", "")).strip()
        clean_t = TopicSummarizationService._clean_title(raw_title)
        title = clean_t if clean_t and len(clean_t) >= 2 else raw_title
        if custom_title and custom_title.strip():
            title = TopicSummarizationService._clean_title(custom_title.strip()) or custom_title.strip()
        if not title or len(title) < 2:
            title = existing_info.get("title") or "话题研读"

        title = TopicSummarizationService._clean_title(title) or "话题研读"
        # Guard: if title is still a placeholder or too short, extract meaningful phrase from discussion
        if len(title) < 2 or title in ("话题研读", "topic", "data", "test", "Topic Workspace") or title.startswith("我想知道") or title.startswith("请问"):
            import re
            # Extract first meaningful noun-phrase from discussion text
            lines = discussion_text.strip().split('\n')
            for line in lines:
                cleaned = re.sub(r'^[问答]:\s*', '', line).strip()
                if cleaned and len(cleaned) >= 4:
                    title = cleaned[:12]
                    break

        description = str(data.get("description", "")).strip()
        if not description or "话题认知:" in description or "围绕「" in description:
            description = f"深入研究与探索「{title}」的核心概念、规范流程与技术细节。"

        soul_content = str(data.get("soul_content", "")).strip()
        if not soul_content or "#" not in soul_content:
            soul_content = f"# 话题认知: {title}\n## 核心实体与领域\n- {title}\n## 场景边界与目标\n- 深入研究与探索「{title}」的核心概念与流程\n## 关键背景摘要\n- 自动提取对话要点与技术脉络"

        tags = data.get("tags", [])
        if isinstance(tags, list):
            cleaned_tags = [TopicSummarizationService._clean_title(str(t)) for t in tags if str(t).strip()]
            tags = [t for t in cleaned_tags if t and len(t) >= 2][:4]
        else:
            tags = []
        if not tags:
            tags = [title[:8]]

        return {
            "title": title,
            "description": description,
            "soul_content": soul_content,
            "tags": tags
        }

    @staticmethod
    def _extract_meaningful_title(discussion_text: str) -> str:
        """Extract a meaningful title snippet from discussion text."""
        import re
        lines = discussion_text.strip().split('\n')
        for line in lines:
            cleaned = re.sub(r'^[问答]:\s*', '', line).strip()
            if cleaned and len(cleaned) >= 4:
                return cleaned[:12]
        return "话题研读"

    @staticmethod
    def _fallback(custom_title: Optional[str], discussion_text: str, existing_info: Dict[str, Any]) -> Dict[str, Any]:
        clean_disc = discussion_text.replace("问:", "").replace("问：", "").replace("答:", "").replace("答：", "").strip()

        if custom_title and custom_title.strip():
            raw_t = custom_title.strip()
        elif existing_info.get("title"):
            existing_t = existing_info["title"]
            if len(existing_t) >= 2 and existing_t not in ("话题研读", "topic", "data"):
                raw_t = existing_t
            else:
                raw_t = TopicSummarizationService._extract_meaningful_title(discussion_text)
        else:
            raw_t = TopicSummarizationService._extract_meaningful_title(discussion_text)

        title = TopicSummarizationService._clean_title(raw_t) or "话题研读"
        return {
            "title": title,
            "description": f"深入研究与探索「{title}」的核心概念、规范流程与技术细节。",
            "soul_content": f"# 话题认知: {title}\n## 核心实体与领域\n- {title}\n## 场景边界与目标\n- 深入研究与探索「{title}」的核心概念与流程\n## 关键背景摘要\n- 自动提取对话要点与技术脉络",
            "tags": [title[:8]]
        }
