"""Model-assisted report synthesis over frozen local evidence only."""

from __future__ import annotations

import json
import re
from urllib.request import Request, urlopen

from .renderer import MarkdownReportRenderer


class EvidenceReportSynthesizer(MarkdownReportRenderer):
    """Synthesize readable prose without expanding the frozen evidence scope."""

    _CITATION = re.compile(r"\[(\d+)\]")

    def __init__(self, *, api_base: str, api_key: str, model: str, timeout_seconds: int = 120) -> None:
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
            f"[{item.number}] {item.title}\n原文：{item.excerpt}"
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
            "Do not output a title, source list, or code fence. If the evidence is insufficient, say exactly "
            "what cannot be confirmed.\n\n"
            f"Question: {kwargs['objective']}\n\nEvidence:\n{evidence_text}"
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 3500,
        }
        try:
            data = self._chat(payload)
            content = str(data["choices"][0]["message"]["content"]).strip()
            if content.startswith("```") and content.endswith("```"):
                content = "\n".join(content.splitlines()[1:-1]).strip()
            content = self._normalize_section_headings(content, language)
            numbers = [int(value) for value in self._CITATION.findall(content)]
            if not content or not numbers or max(numbers) > len(base_report.citations):
                return base_report
        except Exception:
            return base_report

        source_lines = ["", "## 来源" if language == "zh-CN" else "## Sources", ""]
        for citation in base_report.citations:
            source_lines.append(
                f"{citation.number}. **{citation.title}** · "
                f"{citation.document_version or '本地快照'} · {citation.locator}"
            )
        markdown = f"# {kwargs.get('title') or kwargs['objective']}\n\n{content}\n" + "\n".join(source_lines)
        return base_report.model_copy(update={"markdown": markdown.strip() + "\n"})

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
            if stripped.casefold() in heading_set and not line.lstrip().startswith("#"):
                lines.append(f"## {stripped}")
            else:
                lines.append(line)
        return "\n".join(lines)

    def _chat(self, payload: dict) -> dict:
        request = Request(
            f"{self.api_base}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


__all__ = ["EvidenceReportSynthesizer"]
