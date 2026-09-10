import pytest
import sys
from pathlib import Path

# Setup paths
project_root = Path(__file__).resolve().parent.parent
for p in [str(project_root), str(project_root / "data-pipeline"), str(project_root / "data-persistence"), str(project_root / "agent")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from eval.ragas_eval import (
    compute_faithfulness,
    compute_answer_relevance,
    compute_context_precision,
    compute_context_recall,
    compute_semantic_similarity,
    RagasEvaluator
)


def test_semantic_similarity():
    text1 = "项目的 CP1 阶段实现端到端单轮 RAG 闭环"
    text2 = "CP1 阶段完成了单轮 RAG 核心链路"
    text3 = "今天天气晴朗适合出门运动"

    sim_high = compute_semantic_similarity(text1, text2)
    sim_low = compute_semantic_similarity(text1, text3)

    assert sim_high > 0.6
    assert sim_low < sim_high


def test_compute_faithfulness_empty():
    res = compute_faithfulness(answer="", contexts=[])
    assert res["score"] == 0.0


def test_compute_faithfulness_supported():
    contexts = [
        "员工休假需提前3天在内部OA系统提交审批单，由直属主管审批通过后生效。"
    ]
    answer = "员工休假需要提前3天在内部系统提交申请，并经过直属主管审批。"

    res = compute_faithfulness(answer=answer, contexts=contexts)
    assert res["score"] >= 0.7


def test_compute_answer_relevance():
    question = "休假需要提前几天申请？"
    good_answer = "休假需要提前3天在系统提交申请。"
    res = compute_answer_relevance(question=question, answer=good_answer)
    assert res["score"] >= 0.7


def test_compute_context_recall():
    question = "项目的存储架构是怎样的？"
    ground_truth = "使用 Milvus 存储向量切片，使用 SQLite 存储元数据与会话历史。"
    contexts = [
        "Data Persistence 层采用 Milvus 向量库保存 Embedding 向量，并用 SQLite 记录文档元信息和历史对话。"
    ]

    res = compute_context_recall(question=question, contexts=contexts, ground_truth=ground_truth)
    assert res["score"] >= 0.7


def test_ragas_evaluator_dataset_loading():
    dataset_file = Path(__file__).parent / "confluence_eval_dataset.json"
    evaluator = RagasEvaluator(dataset_path=str(dataset_file))
    assert len(evaluator.dataset) > 0
    first_item = evaluator.dataset[0]
    assert "question" in first_item
    assert "ground_truth" in first_item
    assert "category" in first_item
