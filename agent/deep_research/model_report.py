"""Model-assisted report synthesis over frozen local evidence only."""

from __future__ import annotations

import json
import logging
import re
import time
from urllib.request import Request, urlopen

from agent.config.settings import settings
from .renderer import MarkdownReportRenderer


logger = logging.getLogger(__name__)


class EvidenceReportSynthesizer(MarkdownReportRenderer):
    """Synthesize readable prose without expanding the frozen evidence scope."""

    _CITATION = re.compile(r"\[(\d+)\]")

    def __init__(self, *, api_base: str, api_key: str, model: str, timeout_seconds: int = 90) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def render(self, **kwargs):
        language = kwargs.get("language") or "en-US"
        base_report = super().render(**kwargs)
        if not base_report.citations or not self.api_key:
            return base_report

        evidence_text = "\n\n".join(
            f"[{item.number}] {item.title}（{item.document_version or '本地快照'}，{item.locator}）\n原文：{item.excerpt}"
            for item in base_report.citations
        )
        output_instruction = (
            "Write a complete Chinese research report with these sections: 结论摘要、关键发现、逐项分析、冲突与处理、局限与待确认事项. "
            "Use tables when they make comparisons clearer. Explain conditions, dates, versions, and exceptions instead of only giving a direct answer."
            if language == "zh-CN"
            else "Write a complete research report with these sections: Executive summary, Key findings, Detailed analysis, Conflicts and resolution, and Limitations. "
            "Use tables when they make comparisons clearer. Explain conditions, dates, versions, and exceptions instead of only giving a direct answer."
        )
        prompt = (
            "You are a rigorous research report writer. Use only the frozen, verified local evidence below. "
            "Do not browse, add facts from memory, or invent sources. "
            f"{output_instruction} Every factual paragraph or table row must include its matching [n] citation. "
            "Cover every part of the user's question that the evidence can support, synthesize rather than copy raw Markdown, "
            "and distinguish confirmed facts from pending verification. Do not output a title, source list, or code fence. If the evidence is insufficient, say exactly "
            "what cannot be confirmed. Use level-two Markdown headings (##). "
            "Treat the requested module, period, and frozen source scope as hard constraints. "
            "Never substitute a nearby module or period: if the evidence only covers another "
            "entity, explicitly refuse the requested exact figures and do not put the other "
            "entity's numbers in the conclusion. "
            "Be concise: do not repeat findings across sections; keep the body within "
            "1200 Chinese characters or 700 English words, prioritizing the requested facts.\n\n"
            f"Question: {kwargs['objective']}\n\nEvidence:\n{evidence_text}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 4000,
        }
        if settings.LLM_THINKING_MODE in {"enabled", "disabled"}:
            payload["thinking"] = {"type": settings.LLM_THINKING_MODE}
        try:
            for attempt in range(2):
                data = self._chat(payload)
                choice = data["choices"][0]
                content = str(choice["message"].get("content") or "").strip()
                if content.startswith("```") and content.endswith("```"):
                    content = "\n".join(content.splitlines()[1:-1]).strip()
                content = self._normalize_section_headings(content, language)
                issues = self._structural_issues(content, len(base_report.citations), choice.get("finish_reason"))
                if not issues:
                    break
                if attempt == 0:
                    payload["messages"].extend([
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": "Rewrite the complete report once using exactly the same evidence. "
                         "Fix these structural problems: " + "; ".join(issues) +
                         ". Answer every requested part or explicitly state it cannot be confirmed. "
                         "Do not invent facts or add citations to unsupported statements."},
                    ])
            if issues:
                logger.warning("Research report model returned an incomplete report (%s); using verified fallback", "; ".join(issues))
                return base_report
        except Exception as exc:
            logger.warning("Research report model failed; using verified fallback: %s", exc)
            return base_report

        source_lines = ["", "## 来源" if language == "zh-CN" else "## Sources", ""]
        for citation in base_report.citations:
            source_lines.append(
                f"{citation.number}. **{citation.title}** · "
                f"{citation.document_version or '本地快照'} · {citation.locator}"
            )
        markdown = f"# {kwargs.get('title') or kwargs['objective']}\n\n{content}\n" + "\n".join(source_lines)
        return base_report.model_copy(update={"markdown": markdown.strip() + "\n"})

    @classmethod
    def _structural_issues(cls, content: str, citation_count: int, finish_reason: str | None) -> list[str]:
        """Structural guard only: it does not claim semantic correctness."""
        issues = []
        numbers = [int(value) for value in cls._CITATION.findall(content)]
        if finish_reason == "length":
            issues.append("generation was truncated")
        if len(content) < 240 or len(re.findall(r"(?m)^##\s+", content)) < 5:
            issues.append("missing report sections or incomplete body")
        if not numbers or any(n < 1 or n > citation_count for n in numbers):
            issues.append("missing or out-of-range citations")
        return issues

    @staticmethod
    def _normalize_section_headings(content: str, language: str) -> str:
        headings = (
            ["结论摘要", "关键发现", "逐项分析", "分析过程", "关键证据", "适用条件与例外", "冲突与处理", "冲突与不确定性", "局限与待确认事项", "局限与后续建议"]
            if language == "zh-CN"
            else ["Executive summary", "Key findings", "Detailed analysis", "Analysis", "Key evidence", "Conditions and exceptions", "Conflicts and resolution", "Conflicts and uncertainty", "Limitations", "Limitations and next steps"]
        )
        heading_set = {item.casefold() for item in headings}
        lines = []
        for line in content.splitlines():
            stripped = line.strip().rstrip(":：")
            stripped = re.sub(r"^#{1,6}\s*", "", stripped).strip("*")
            stripped = re.sub(r"^\d+[.、)]\s*", "", stripped).strip()
            if stripped.casefold() in heading_set:
                lines.append(f"## {stripped}")
            else:
                lines.append(line)
        return "\n".join(lines)

    def _chat(self, payload: dict) -> dict:
        last_error: Exception | None = None
        for attempt in range(2):
            request = Request(
                f"{self.api_base}/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    logger.warning("Research report request failed; retrying once: %s", exc)
                    time.sleep(0.5)
        assert last_error is not None
        raise last_error


__all__ = ["EvidenceReportSynthesizer"]
