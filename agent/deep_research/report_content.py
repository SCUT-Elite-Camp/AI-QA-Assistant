"""Report block editing and structural checks shared by the Research harness."""
import json
import re


class ReportContent:
    _CITATION = re.compile(r"\[(\d+)\]")

    @staticmethod
    def _editable_blocks(content: str) -> list[dict]:
        sections = re.split(r"(?m)^#{1,6}\s+[^\n]*\n?", content)
        paragraphs = [block.strip() for section in sections for block in section.split("\n\n") if block.strip()]
        return [{"block_id": index, "text": block} for index, block in enumerate(paragraphs)]

    @staticmethod
    def _apply_grounding_edits(content: str, raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.splitlines()[1:-1])
        edit_result = json.loads(raw)
        if not isinstance(edit_result, dict):
            raise ValueError("invalid grounding edits")
        edits = edit_result.get("edits")
        if not isinstance(edits, list) or not 1 <= len(edits) <= 8:
            raise ValueError("invalid grounding edits")
        blocks = ReportContent._editable_blocks(content)
        used_blocks = set()
        for edit in edits:
            if not isinstance(edit, dict):
                raise ValueError("invalid grounding edit item")
            if "block_id" in edit:
                index = edit["block_id"]
                if type(index) is not int or not 0 <= index < len(blocks) or index in used_blocks:
                    raise ValueError("invalid grounding block id")
                used_blocks.add(index)
                edit = {"original": blocks[index]["text"], "replacement": edit.get("replacement")}
            original, replacement = edit.get("original"), edit.get("replacement")
            if (not isinstance(original, str) or not original.strip() or not isinstance(replacement, str)
                    or len(original) > 2000 or "\n\n" in original
                    or original.lstrip().startswith("#") or re.search(r"(?m)^#", replacement)
                    or content.count(original) != 1):
                raise ValueError("grounding edit must target a unique factual block")
            if original == replacement:
                continue
            content = content.replace(original, replacement, 1)
        return content

    @classmethod
    def _structural_issues(
        cls,
        content: str,
        citation_count: int,
        finish_reason: str | None,
        *,
        evidence_text: str = "",
        language: str | None = None,
    ) -> list[str]:
        """Reject structurally unsafe output and obvious source-copy reports."""
        issues = []
        narrative = re.sub(r"`[^`]*`", "", content)
        if evidence_text:
            narrative = re.sub(r'["“]([^"”\n]+)["”]', lambda match: '' if match.group(1).rstrip(',，.;； ') in evidence_text else match.group(), narrative)
        if language == "en-US" and re.search(r"[\u3400-\u9fff]", narrative):
            issues.append("report narrative must be in English")
        numbers = [int(value) for value in cls._CITATION.findall(content)]
        if finish_reason == "length":
            issues.append("generation was truncated")
        if len(content) < 240 or len(re.findall(r"(?m)^##\s+", content)) < (3 if language == "en-US" else 5):
            issues.append("missing report sections or incomplete body")
        if not numbers or any(n < 1 or n > citation_count for n in numbers):
            issues.append("missing or out-of-range citations")
        if not cls._all_factual_blocks_are_cited(content):
            issues.append("one or more factual blocks lack citations")
        if evidence_text and cls._copied_evidence_blocks(content, evidence_text):
            issues.append("report copies long evidence blocks instead of synthesizing them")
        return issues

    @classmethod
    def _copied_evidence_blocks(cls, content: str, evidence_text: str) -> list[str]:
        """Find long report blocks copied nearly verbatim from frozen evidence."""

        normalized_evidence = cls._normalize_copy_text(evidence_text)
        copied: list[str] = []
        for block in re.split(r"\n\s*\n", content):
            text = block.strip()
            if not text or text.startswith("#"):
                continue
            without_citations = cls._CITATION.sub("", text)
            normalized = cls._normalize_copy_text(without_citations)
            # Short names, figures and table rows legitimately match sources.
            # A 60-character prose/list block (already substantial in Chinese)
            # should be synthesized instead of copied verbatim.
            if len(normalized) >= 60 and normalized in normalized_evidence:
                copied.append(text)
        return copied

    @staticmethod
    def _normalize_copy_text(value: str) -> str:
        return re.sub(r"\s+", "", value).casefold()

    @classmethod
    def _all_factual_blocks_are_cited(cls, content: str) -> bool:
        """Require citations on prose/list/table blocks that contain assertions."""

        return not cls._uncited_factual_blocks(content)

    @classmethod
    def _uncited_factual_blocks(cls, content: str) -> list[str]:
        """Return concrete factual blocks that have no citation marker."""

        uncited = []
        for block in re.split(r"\n\s*\n", content):
            # A model may omit the blank line after a heading. Strip only
            # heading lines; skipping the whole block would also skip its
            # factual paragraph and silently accept missing citations.
            text = re.sub(r'(?m)^#{1,6}\s+[^\n]*(?:\n|$)', '', block).strip()
            if not text:
                continue
            # Pure section labels and explicit insufficiency statements do not
            # introduce facts. Everything else must remain traceable.
            if any(marker in text for marker in ("无法确认", "资料不足", "cannot confirm", "insufficient evidence")):
                continue
            if cls._block_requires_citation(text) and not cls._CITATION.search(text):
                uncited.append(text)
        return uncited

    @staticmethod
    def _block_requires_citation(text: str) -> bool:
        """Distinguish concrete factual content from connective report prose."""

        if re.search(r"(?m)^(?:[-*+]\s+|\|.+\|)", text):
            return True
        if re.search(r"\d|`[^`]+`", text):
            return True
        factual_markers = (
            "Finished", "Not started", "In progress", "提交", "作者", "日期",
            "版本", "文件", "状态", "数量", "总计", "增加", "减少",
            "completed", "author", "date", "version", "file", "status",
        )
        return any(marker.casefold() in text.casefold() for marker in factual_markers)

    @staticmethod
    def _normalize_section_headings(content: str, language: str) -> str:
        headings = (
            ["结论摘要", "关键发现", "逐项分析", "分析过程", "关键证据", "适用条件与例外", "冲突与处理", "冲突与不确定性", "局限与待确认事项", "局限与后续建议"]
            if language == "zh-CN"
            else ["Summary", "Evidence and analysis", "Limitations and uncertainty", "Executive summary", "Key findings", "Detailed analysis", "Analysis", "Key evidence", "Conditions and exceptions", "Conflicts and resolution", "Conflicts and uncertainty", "Limitations", "Limitations and next steps"]
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
