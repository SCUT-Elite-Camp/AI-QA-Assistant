import os
import sys
import json
import time
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

project_root = Path(__file__).resolve().parent.parent
python_paths = [
    str(project_root),
    str(project_root / "data-pipeline"),
    str(project_root / "data-persistence"),
    str(project_root / "toolset"),
    str(project_root / "agent")
]
for p in python_paths:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
agent_env_path = project_root / "agent" / ".env"
if agent_env_path.exists():
    load_dotenv(dotenv_path=agent_env_path)

from tool_layer.search_tool import SearchTool
from agent.agent import Agent
from agent.schemas.chat import ChatRequest
from agent.llm.llm_client import LLMClient


def run_benchmark():
    dataset_file = project_root / "eval" / "confluence_eval_dataset.json"
    with open(dataset_file, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    print("=" * 70)
    print(f"🚀 开始执行 AI-QA-Assistant 全量基准测试（共 {len(dataset)} 个真实用例）")
    print("=" * 70)

    search_tool = SearchTool()
    agent = Agent()
    llm_client = LLMClient()

    results = []

    for idx, item in enumerate(dataset, 1):
        q_id = item["id"]
        category = item["category"]
        question = item["question"]
        ground_truth = item["ground_truth"]

        print(f"\n[{idx}/{len(dataset)}] 正在测试: {question} (类别: {category})")

        # ----------------------------------------------------
        # 1. 运行 Fast 模式 (单轮直接 RAG)
        # ----------------------------------------------------
        t0 = time.perf_counter()
        fast_search_res = search_tool.search(
            query=question,
            top_k=4,
            mode="hybrid",
            weight_mode="fast"
        )
        fast_contexts = []
        for c in fast_search_res:
            t = c.get("chunk_text") or c.get("text") or c.get("snippet") or c.get("content") or ""
            if t.strip():
                doc_meta = search_tool._load_document_meta(str(c.get("doc_id", ""))) if hasattr(search_tool, "_load_document_meta") else {}
                title = c.get("title") or (doc_meta.get("title") if doc_meta else "") or ""
                fast_contexts.append({
                    "title": title,
                    "doc_id": c.get("doc_id"),
                    "chunk_id": c.get("chunk_id"),
                    "score": c.get("score"),
                    "text": t
                })

        ctx_str = "\n\n".join([f"[{i+1}] 标题: {c['title']}\n内容: {c['text']}" for i, c in enumerate(fast_contexts)]) if fast_contexts else "无相关参考文档"
        fast_prompt = f"""你是一个专业的智能问答助手。请根据以下参考文档直接、准确地回答用户问题。如果文档中没有明确提及，请如实说明，不要编造。

【参考文档】：
{ctx_str}

【用户问题】：
{question}
"""
        try:
            fast_answer = llm_client.generate(fast_prompt)
        except Exception as e:
            fast_answer = f"Error generating answer: {e}"
        fast_latency = (time.perf_counter() - t0) * 1000.0
        print(f"  ├─ [Fast Mode]     完成 | 耗时: {fast_latency:.1f}ms")

        # ----------------------------------------------------
        # 2. 运行 Thinking 模式 (深度 Agent 编排)
        # ----------------------------------------------------
        t1 = time.perf_counter()
        try:
            req = ChatRequest(
                query=question,
                retrieval_mode="hybrid",
                weight_mode="thinking",
                top_k=4
            )
            resp = agent.chat(req)
            thinking_answer = getattr(resp, "answer", str(resp))
            thinking_citations = [c.model_dump() for c in resp.citations] if hasattr(resp, "citations") and resp.citations else []
            thinking_status = getattr(resp, "status", "success")
        except Exception as e:
            thinking_answer = f"Error in Agent: {e}"
            thinking_citations = []
            thinking_status = "error"
        thinking_latency = (time.perf_counter() - t1) * 1000.0
        print(f"  └─ [Thinking Mode] 完成 | 耗时: {thinking_latency:.1f}ms")

        results.append({
            "id": q_id,
            "category": category,
            "question": question,
            "ground_truth": ground_truth,
            "expected_keywords": item.get("expected_keywords", []),
            "fast_mode": {
                "answer": fast_answer,
                "latency_ms": fast_latency,
                "contexts": fast_contexts
            },
            "thinking_mode": {
                "answer": thinking_answer,
                "latency_ms": thinking_latency,
                "citations": thinking_citations,
                "status": thinking_status
            }
        })

    # 保存原始测试结果
    out_dir = project_root / "eval" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_file = out_dir / "raw_benchmark_results.json"
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_samples": len(results),
            "samples": results
        }, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 70)
    print(f"✅ 全量基准测试运行完毕！原始数据已保存至: {raw_file}")
    print("=" * 70)


if __name__ == "__main__":
    run_benchmark()
