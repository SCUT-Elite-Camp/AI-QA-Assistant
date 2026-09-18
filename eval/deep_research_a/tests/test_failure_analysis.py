from eval.deep_research_a.analyze_failures import analyze


def test_analyze_groups_root_causes_and_gate_failures() -> None:
    scores = [
        {
            "group": "G2", "case_id": "DR-A-001", "hard_gate_pass": False,
            "root_cause": "RETRIEVAL_DOCUMENT_MISS",
            "failure_codes": ["RETRIEVAL_DOCUMENT_MISS", "REPORT_INCOMPLETE"],
            "hard_gates": {"faithfulness": {"passed": False}},
        },
        {
            "group": "G2", "case_id": "DR-A-002", "hard_gate_pass": True,
            "root_cause": None, "failure_codes": [],
            "hard_gates": {"faithfulness": {"passed": True}},
        },
    ]
    report = analyze(scores)["groups"]["G2"]
    assert report["hard_gate_pass_count"] == 1
    assert report["root_causes"] == {"RETRIEVAL_DOCUMENT_MISS": 1, "PASS": 1}
    assert report["hard_gate_failures"] == {"faithfulness": 1}
