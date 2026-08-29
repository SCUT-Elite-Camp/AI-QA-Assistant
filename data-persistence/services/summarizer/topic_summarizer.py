import os
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

# Load env configuration from agent/.env and root .env
for env_path in [
    Path(__file__).resolve().parent.parent.parent.parent / "agent" / ".env",
    Path(__file__).resolve().parent.parent.parent.parent / ".env",
    Path.cwd() / "agent" / ".env",
    Path.cwd() / ".env"
]:
    if env_path.exists():
        load_dotenv(env_path)
load_dotenv()

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.longcat.chat/openai/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "LongCat-2.0")


def _get_topics_base_dir() -> Path:
    cwd = Path.cwd()
    if cwd.name in ["web", "agent", "toolset", "data-pipeline"]:
        cwd = cwd.parent
    topics_dir = cwd / "data-persistence" / "data" / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    return topics_dir


def _call_llm(messages: List[Dict[str, str]], max_tokens: int = 2500, temperature: float = 0.2) -> str:
    """Call LLM API for topic summarization and cognition generation."""
    env_file = Path(__file__).resolve().parent.parent.parent.parent / "agent" / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)
    load_dotenv(override=True)

    api_key = os.getenv("LLM_API_KEY", "")
    api_base = os.getenv("LLM_API_BASE", "https://api.longcat.chat/openai/v1")
    model = os.getenv("LLM_MODEL", "LongCat-2.0")

    if not api_key:
        print("[TopicSummarizer] Error: LLM_API_KEY is not set in environment!")
        return ""

    try:
        url = f"{api_base.rstrip('/')}/chat/completions"
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                msg = data.get("choices", [{}])[0].get("message", {})
                content = (msg.get("content") or "").strip()
                if content:
                    return content
                
                # Handle reasoning models where output is in reasoning_content
                reasoning = (msg.get("reasoning_content") or "").strip()
                if reasoning:
                    return reasoning
    except Exception as err:
        print(f"[TopicSummarizer] LLM API call error: {err}")
    return ""


class TopicSummarizer:
    """
    Data Persistence Layer Infrastructure Service:
    Executes a single structured LLM request to extract discussion content and reference existing topic state,
    generating Title, Description, System Core Cognition (Soul.md), and Content Tags.
    Directly persists generated artifacts to data-persistence/data/topics/<topic_id>/
    """

    @classmethod
    def summarize_and_persist(
        cls,
        topic_id: str,
        discussion_text: str,
        custom_title: Optional[str] = None,
        existing_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        topics_base = _get_topics_base_dir()
        topic_dir = topics_base / topic_id
        topic_dir.mkdir(parents=True, exist_ok=True)
        docs_dir = topic_dir / "documents"
        docs_dir.mkdir(parents=True, exist_ok=True)

        if custom_title and (custom_title.startswith("我想知道") or custom_title.startswith("请问") or custom_title == "新对话"):
            custom_title = None

        # 1. Read existing topic info if present on disk if not provided
        if not existing_info:
            info_file = topic_dir / "topic_info.json"
            soul_file = topic_dir / "soul.md"
            if info_file.exists():
                try:
                    with open(info_file, "r", encoding="utf-8") as f:
                        existing_info = json.load(f)
                except Exception:
                    pass
            if not existing_info:
                existing_info = {}
            if soul_file.exists() and "soulContent" not in existing_info:
                try:
                    with open(soul_file, "r", encoding="utf-8") as f:
                        existing_info["soulContent"] = f.read()
                except Exception:
                    pass

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
            raw_resp = _call_llm(messages, max_tokens=2500, temperature=0.2)
            if raw_resp and raw_resp.strip():
                break
            print(f"[TopicSummarizer] Warning: LLM returned empty response on attempt {attempt + 1}, retrying...")
        
        parsed = cls._parse_and_verify_json(raw_resp, custom_title, discussion_text, existing_info)

        title = parsed["title"]
        description = parsed["description"]
        soul_content = parsed["soul_content"]
        tags = parsed["tags"]

        # 3. Write soul.md & topic_info.json directly to disk
        soul_path = topic_dir / "soul.md"
        with open(soul_path, "w", encoding="utf-8") as f:
            f.write(soul_content)

        import datetime
        now_str = datetime.datetime.now().isoformat()
        info_data = {
            "id": topic_id,
            "title": title,
            "description": description,
            "soulContent": soul_content,
            "tags": tags,
            "weightMode": existing_info.get("weightMode", "auto"),
            "consecutiveNoNewDocsCount": existing_info.get("consecutiveNoNewDocsCount", 0),
            "last_synced_at": now_str
        }
        info_path = topic_dir / "topic_info.json"
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(info_data, f, ensure_ascii=False, indent=2)

        return info_data


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
            return TopicSummarizer._fallback(custom_title, discussion_text, existing_info)

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
                        print(f"[TopicSummarizer] JSON parse verification failed: {e}")

        if not data or not isinstance(data, dict):
            return TopicSummarizer._fallback(custom_title, discussion_text, existing_info)

        raw_title = str(data.get("title", "")).strip()
        clean_t = TopicSummarizer._clean_title(raw_title)
        title = clean_t if clean_t and len(clean_t) >= 2 else raw_title
        if custom_title and custom_title.strip():
            title = TopicSummarizer._clean_title(custom_title.strip()) or custom_title.strip()
        if not title or len(title) < 2:
            title = existing_info.get("title") or "话题研读"

        title = TopicSummarizer._clean_title(title) or "话题研读"
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
            cleaned_tags = [TopicSummarizer._clean_title(str(t)) for t in tags if str(t).strip()]
            tags = [t for t in cleaned_tags if t and len(t) >= 2][:4]
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
                raw_t = TopicSummarizer._extract_meaningful_title(discussion_text)
        else:
            raw_t = TopicSummarizer._extract_meaningful_title(discussion_text)

        title = TopicSummarizer._clean_title(raw_t) or "话题研读"
        return {
            "title": title,
            "description": f"深入研究与探索「{title}」的核心概念、规范流程与技术细节。",
            "soul_content": f"# 话题认知: {title}\n## 核心实体与领域\n- {title}\n## 场景边界与目标\n- 深入研究与探索「{title}」的核心概念与流程\n## 关键背景摘要\n- 自动提取对话要点与技术脉络",
            "tags": [title[:8]]
        }
