from deep_research.model_report import EvidenceReportSynthesizer


def test_report_quality_gate_requires_citation_on_each_factual_block() -> None:
    assert EvidenceReportSynthesizer._all_factual_blocks_are_cited(
        "## 结论摘要\n\nW30 有 9 次提交。[1]\n\nW34 有 8 次提交。[2]"
    )
    assert not EvidenceReportSynthesizer._all_factual_blocks_are_cited(
        "## 结论摘要\n\nW30 有 9 次提交。[1]\n\nW34 有 8 次提交。"
    )


def test_report_quality_gate_allows_explicit_unknowns_without_citation() -> None:
    assert EvidenceReportSynthesizer._all_factual_blocks_are_cited(
        "## 局限与待确认事项\n\n现有资料不足，无法确认生产性能。"
    )


def test_report_quality_gate_allows_non_factual_transition_but_not_status_claim() -> None:
    assert EvidenceReportSynthesizer._all_factual_blocks_are_cited(
        "## 逐项分析\n\n下面按问题要求逐项说明。"
    )
    assert not EvidenceReportSynthesizer._all_factual_blocks_are_cited(
        "## 逐项分析\n\nAG-M10 的状态为 Not started。"
    )
    assert EvidenceReportSynthesizer._uncited_factual_blocks(
        "## 逐项分析\n\nAG-M10 的状态为 Not started。"
    ) == ["AG-M10 的状态为 Not started。"]


def test_report_quality_gate_rejects_long_verbatim_evidence_block() -> None:
    source = (
        "原文：W34 Agent 模块总提交为 8，其中新功能 3、Bug 修复 5、其他改进 0。"
        "该周还完成了流式输出和引用构建，并记录了各项提交信息。"
    )
    copied = (
        "## 关键发现\n\n"
        "W34 Agent 模块总提交为 8，其中新功能 3、Bug 修复 5、其他改进 0。"
        "该周还完成了流式输出和引用构建，并记录了各项提交信息。[1]"
    )
    assert EvidenceReportSynthesizer._copied_evidence_blocks(copied, source)
    assert "report copies long evidence blocks instead of synthesizing them" in (
        EvidenceReportSynthesizer._structural_issues(
            copied + "\n\n## 结论摘要\n\n见上。[1]\n\n## 逐项分析\n\n见上。[1]"
            "\n\n## 冲突与处理\n\n无冲突。[1]\n\n## 局限与待确认事项\n\n无。[1]",
            1,
            "stop",
            evidence_text=source,
        )
    )


def test_report_quality_gate_allows_concise_synthesis_of_same_facts() -> None:
    source = (
        "原文：W34 Agent 模块总提交为 8，其中新功能 3、Bug 修复 5、其他改进 0。"
        "该周还完成了流式输出和引用构建，并记录了各项提交信息。"
    )
    synthesis = "## 结论摘要\n\nW34 共 8 次提交，以修复为主（5 次）。[1]"
    assert not EvidenceReportSynthesizer._copied_evidence_blocks(synthesis, source)
