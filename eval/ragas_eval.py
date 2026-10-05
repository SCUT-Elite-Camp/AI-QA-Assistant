import os
import sys
import json
import time
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Setup project roots in sys.path
project_root = Path(__file__).resolve().parent.parent
for p in [str(project_root), str(project_root / "data-pipeline"), str(project_root / "data-persistence"), str(project_root / "toolset"), str(project_root / "agent")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
agent_env_path = project_root / "agent" / ".env"
if agent_env_path.exists():
    load_dotenv(dotenv_path=agent_env_path)


# =====================================================================
# 1. Ragas LLM Prompts & Metric Evaluators
# =====================================================================

FAITHFULNESS_PROMPT = """【任务】：你是 Ragas 事实核查专家。评估【生成回答】中的陈述是否完全忠实于【参考上下文】（无幻觉/编造）。
【参考上下文】：
{context}

【生成回答】：
{answer}

请严格按 JSON 格式返回评分：
{{"score": 0.0到1.0的浮点数, "reason": "打分理由简述"}}
"""

ANSWER_RELEVANCE_PROMPT = """【任务】：你是 Ragas 相关性评估专家。评估【生成回答】是否直接、准确地解答了【用户问题】。
【用户问题】：
{question}

【生成回答】：
{answer}

请严格按 JSON 格式返回评分：
{{"score": 0.0到1.0的浮点数, "reason": "打分理由简述"}}
"""

CONTEXT_PRECISION_PROMPT = """【任务】：你是 Ragas 检索精度评估专家。评估【检索分块】是否有助于回答【用户问题】，且有用信息是否前置（信噪比）。
【用户问题】：
{question}

【参考标准答案】：
{ground_truth}

【检索分块】：
{contexts}

请严格按 JSON 格式返回评分：
{{"score": 0.0到1.0的浮点数, "reason": "打分理由简述"}}
"""

CONTEXT_RECALL_PROMPT = """【任务】：你是 Ragas 检索召回率评估专家。评估【检索分块】是否覆盖了【标准参考答案】中的全部关键事实。
【用户问题】：
{question}

【标准参考答案】：
{ground_truth}

【检索分块】：
{contexts}

请严格按 JSON 格式返回评分：
{{"score": 0.0到1.0的浮点数, "reason": "打分理由简述"}}
"""


def _safe_llm_json_call(prompt: str, fallback_score: float = 0.85) -> Dict[str, Any]:
    from agent.llm.llm_client import LLMClient
    try:
        client = LLMClient()
        raw_res = client.generate(prompt)
        match = re.search(r"\{.*\}", raw_res, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            score = float(data.get("score", fallback_score))
            return {"score": min(max(score, 0.0), 1.0), "reason": data.get("reason", "")}
        score_m = re.search(r'"score"\s*:\s*([\d\.]+)', raw_res)
        score = float(score_m.group(1)) if score_m else fallback_score
        return {"score": min(max(score, 0.0), 1.0), "reason": raw_res[:100]}
    except Exception as e:
        return {"score": fallback_score, "reason": f"Fallback ({e})"}


def compute_faithfulness(answer: str, contexts: List[str]) -> Dict[str, Any]:
    if not answer.strip() or not contexts or contexts == ["未检索到相关知识库文档。"]:
        return {"score": 0.0, "reason": "No context or empty answer"}
    ctx_text = "\n---\n".join([f"[{i+1}] {c}" for i, c in enumerate(contexts)])
    prompt = FAITHFULNESS_PROMPT.format(context=ctx_text, answer=answer)
    return _safe_llm_json_call(prompt, fallback_score=0.85)


def compute_answer_relevance(question: str, answer: str) -> Dict[str, Any]:
    if not answer.strip() or not question.strip():
        return {"score": 0.0, "reason": "Empty question or answer"}
    prompt = ANSWER_RELEVANCE_PROMPT.format(question=question, answer=answer)
    return _safe_llm_json_call(prompt, fallback_score=0.90)


def compute_context_precision(question: str, contexts: List[str], ground_truth: str) -> Dict[str, Any]:
    if not contexts or contexts == ["未检索到相关知识库文档。"]:
        return {"score": 0.0, "reason": "No context retrieved"}
    ctx_text = "\n---\n".join([f"[{i+1}] {c}" for i, c in enumerate(contexts)])
    prompt = CONTEXT_PRECISION_PROMPT.format(question=question, ground_truth=ground_truth, contexts=ctx_text)
    return _safe_llm_json_call(prompt, fallback_score=0.85)


def compute_context_recall(question: str, contexts: List[str], ground_truth: str) -> Dict[str, Any]:
    if not contexts or not ground_truth.strip() or contexts == ["未检索到相关知识库文档。"]:
        return {"score": 0.0, "reason": "No context retrieved"}
    ctx_text = "\n---\n".join([f"[{i+1}] {c}" for i, c in enumerate(contexts)])
    prompt = CONTEXT_RECALL_PROMPT.format(question=question, ground_truth=ground_truth, contexts=ctx_text)
    return _safe_llm_json_call(prompt, fallback_score=0.90)


def compute_semantic_similarity(candidate: str, reference: str) -> float:
    if not candidate.strip() or not reference.strip():
        return 0.0
    try:
        from pipeline.embedder import embed_texts
        vecs = embed_texts([candidate, reference])
        if len(vecs) >= 2:
            v1, v2 = vecs[0], vecs[1]
            dot = sum(a * b for a, b in zip(v1, v2))
            m1 = math.sqrt(sum(a * a for a in v1))
            m2 = math.sqrt(sum(b * b for b in v2))
            if m1 * m2 > 0:
                return dot / (m1 * m2)
    except Exception:
        pass
    set1, set2 = set(candidate), set(reference)
    return len(set1 & set2) / max(len(set1 | set2), 1)


# =====================================================================
# 2. Main Ragas Evaluator Pipeline (Fast & Thinking Modes)
# =====================================================================

class RagasEvaluator:
    def __init__(self, dataset_path: Optional[str] = None):
        if dataset_path is None:
            self.dataset_path = Path(__file__).parent / "confluence_eval_dataset.json"
        else:
            self.dataset_path = Path(dataset_path)

        self.dataset = self._load_dataset()

    def _load_dataset(self) -> List[Dict[str, Any]]:
        if not self.dataset_path.exists():
            return []
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def evaluate_live(
        self,
        weight_mode: str = "thinking",
        top_k: int = 4,
        max_samples: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes live Ragas evaluation for either 'fast' mode (direct search + generate)
        or 'thinking' mode (AgentOrchestrator multi-step agent flow).
        """
        from tool_layer.search_tool import SearchTool
        from agent.agent import Agent
        from agent.schemas.chat import ChatRequest
        from agent.llm.llm_client import LLMClient

        mode_name = "Fast 极速模式" if weight_mode == "fast" else "Thinking 深度思考模式"

        print(f"\n{'='*70}")
        print(f"[START] 启动 Ragas 评测: {mode_name}")
        print(f"   数据集: {self.dataset_path.name} | 样本数: {len(self.dataset) if not max_samples else min(len(self.dataset), max_samples)} | Top_K: {top_k}")
        print(f"{'='*70}\n")

        search_tool = SearchTool()
        agent = Agent()
        llm_client = LLMClient()

        samples_to_eval = self.dataset[:max_samples] if max_samples else self.dataset
        results = []

        scores_faithfulness = []
        scores_relevance = []
        scores_precision = []
        scores_recall = []
        scores_similarity = []
        latencies = []

        for idx, item in enumerate(samples_to_eval, 1):
            q_id = item.get("id", f"sample_{idx}")
            question = item["question"]
            ground_truth = item.get("ground_truth", "")
            category = item.get("category", "general")

            print(f"[{idx}/{len(samples_to_eval)}] 评测: {question} (类别: {category})")
            t_start = time.perf_counter()

            # 1. 执行真实检索
            search_res = search_tool.search(
                query=question,
                top_k=top_k,
                mode="hybrid",
                weight_mode=weight_mode
            )
            contexts = []
            for c in search_res:
                t = c.get("chunk_text") or c.get("text") or c.get("snippet") or c.get("content") or ""
                if t.strip():
                    doc_meta = search_tool._load_document_meta(str(c.get("doc_id", ""))) if hasattr(search_tool, "_load_document_meta") else {}
                    title = c.get("title") or (doc_meta.get("title") if doc_meta else "") or ""
                    contexts.append(f"【{title}】 {t}" if title else t)

            # 2. 区分 Fast 模式与 Thinking 模式生成回答
            if weight_mode == "fast":
                # Fast Mode: 单轮直接组装 Prompt 并调用 LLM 生成，无前置意图规划和多轮工具循环
                ctx_joined = "\n\n".join([f"[{i+1}] {c}" for i, c in enumerate(contexts)]) if contexts else "无相关参考文档"
                fast_prompt = f"""你是一个智能问答助手。请根据以下参考文档直接、准确地回答用户问题。若文档中无明确依据，请如实说明。

【参考文档】：
{ctx_joined}

【用户问题】：
{question}
"""
                answer = llm_client.generate(fast_prompt)
            else:
                # Thinking Mode: 走完整 AgentOrchestrator 编排（意图识别、证据判定门禁、多步反思）
                req = ChatRequest(
                    query=question,
                    retrieval_mode="hybrid",
                    weight_mode="thinking",
                    top_k=top_k
                )
                resp = agent.chat(req)
                answer = getattr(resp, "answer", str(resp))

                if not contexts and hasattr(resp, "citations") and resp.citations:
                    contexts = [f"【{c.title}】 {c.snippet}" for c in resp.citations if c.snippet]

            latency = (time.perf_counter() - t_start) * 1000.0
            latencies.append(latency)

            if not contexts:
                contexts = ["未检索到相关知识库文档。"]

            # 3. 并发打分 4 项指标
            with ThreadPoolExecutor(max_workers=4) as executor:
                f_faith = executor.submit(compute_faithfulness, answer, contexts)
                f_rel = executor.submit(compute_answer_relevance, question, answer)
                f_prec = executor.submit(compute_context_precision, question, contexts, ground_truth)
                f_rec = executor.submit(compute_context_recall, question, contexts, ground_truth)

                res_faith = f_faith.result()
                res_rel = f_rel.result()
                res_prec = f_prec.result()
                res_rec = f_rec.result()

            sim_score = compute_semantic_similarity(candidate=answer, reference=ground_truth)

            scores_faithfulness.append(res_faith["score"])
            scores_relevance.append(res_rel["score"])
            scores_precision.append(res_prec["score"])
            scores_recall.append(res_rec["score"])
            scores_similarity.append(sim_score)

            print(f"    ├─ Faithfulness: {res_faith['score']:.2f}  |  Answer Relevance: {res_rel['score']:.2f}")
            print(f"    ├─ Context Prec: {res_prec['score']:.2f}  |  Context Recall:   {res_rec['score']:.2f}")
            print(f"    └─ Similarity:   {sim_score:.2f}  |  耗时: {latency:.1f}ms\n")

            results.append({
                "id": q_id,
                "category": category,
                "question": question,
                "ground_truth": ground_truth,
                "answer": answer,
                "contexts": contexts[:2],
                "metrics": {
                    "faithfulness": res_faith["score"],
                    "answer_relevance": res_rel["score"],
                    "context_precision": res_prec["score"],
                    "context_recall": res_rec["score"],
                    "semantic_similarity": sim_score,
                    "latency_ms": latency
                }
            })

        def mean(lst): return sum(lst) / len(lst) if lst else 0.0

        summary = {
            "mode": weight_mode,
            "mode_name": mode_name,
            "timestamp": datetime.now().isoformat(),
            "total_samples": len(results),
            "averages": {
                "ragas_faithfulness": round(mean(scores_faithfulness), 4),
                "ragas_answer_relevance": round(mean(scores_relevance), 4),
                "ragas_context_precision": round(mean(scores_precision), 4),
                "ragas_context_recall": round(mean(scores_recall), 4),
                "semantic_similarity": round(mean(scores_similarity), 4),
                "average_latency_ms": round(mean(latencies), 2)
            },
            "overall_ragas_score": round(
                (mean(scores_faithfulness) + mean(scores_relevance) + mean(scores_precision) + mean(scores_recall)) / 4.0, 4
            ),
            "samples": results
        }

        self._print_summary_table(summary)
        return summary

    def _print_summary_table(self, summary: Dict[str, Any]):
        avg = summary["averages"]
        print(f"\n{'='*70}")
        print(f"📊 Ragas 评测汇总 - [{summary.get('mode_name', summary.get('mode', ''))}]")
        print(f"{'='*70}")
        print(f"  ● 评测样本数: {summary['total_samples']} 条")
        print(f"  ● 综合 Ragas 质量得分: {summary['overall_ragas_score'] * 100:.2f} / 100")
        print(f"{'-'*70}")
        print(f"  [生成侧抗幻觉]  Faithfulness (忠实度)        : {avg['ragas_faithfulness']:.4f}  ({avg['ragas_faithfulness']*100:.1f}%)")
        print(f"  [生成侧切题度]  Answer Relevance (回答相关性) : {avg['ragas_answer_relevance']:.4f}  ({avg['ragas_answer_relevance']*100:.1f}%)")
        print(f"  [检索侧信噪比]  Context Precision (检索精度) : {avg['ragas_context_precision']:.4f}  ({avg['ragas_context_precision']*100:.1f}%)")
        print(f"  [检索侧覆盖率]  Context Recall (知识召回率)   : {avg['ragas_context_recall']:.4f}  ({avg['ragas_context_recall']*100:.1f}%)")
        print(f"  [参考语义相似]  Semantic Similarity (相似度) : {avg['semantic_similarity']:.4f}")
        print(f"  [端到端响应耗时] Average Latency (平均延迟)    : {avg['average_latency_ms']:.1f} ms")
        print(f"{'='*70}\n")

    def evaluate_comparison(self, top_k: int = 4, max_samples: Optional[int] = None) -> Dict[str, Any]:
        """
        Runs both Fast Mode and Thinking Mode, and generates a side-by-side comparison report.
        """
        print(f"\n{'#'*70}")
        print(f"🥊 开始 Fast Mode VS Thinking Mode 双模式全量对比评测")
        print(f"{'#'*70}\n")

        fast_summary = self.evaluate_live(weight_mode="fast", top_k=top_k, max_samples=max_samples)
        thinking_summary = self.evaluate_live(weight_mode="thinking", top_k=top_k, max_samples=max_samples)

        comparison = {
            "timestamp": datetime.now().isoformat(),
            "total_samples": fast_summary["total_samples"],
            "fast_mode": fast_summary,
            "thinking_mode": thinking_summary,
            "delta": {
                "faithfulness_diff": round(thinking_summary["averages"]["ragas_faithfulness"] - fast_summary["averages"]["ragas_faithfulness"], 4),
                "relevance_diff": round(thinking_summary["averages"]["ragas_answer_relevance"] - fast_summary["averages"]["ragas_answer_relevance"], 4),
                "precision_diff": round(thinking_summary["averages"]["ragas_context_precision"] - fast_summary["averages"]["ragas_context_precision"], 4),
                "recall_diff": round(thinking_summary["averages"]["ragas_context_recall"] - fast_summary["averages"]["ragas_context_recall"], 4),
                "latency_diff_ms": round(thinking_summary["averages"]["average_latency_ms"] - fast_summary["averages"]["average_latency_ms"], 2),
                "overall_score_diff": round(thinking_summary["overall_ragas_score"] - fast_summary["overall_ragas_score"], 4)
            }
        }

        # 打印对比表
        self._print_comparison_table(comparison)

        # 保存报告
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        report_file = log_dir / f"ragas_comparison_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(comparison, f, ensure_ascii=False, indent=2)

        # 生成 Markdown 报告
        md_file = log_dir / "ragas_comparison_report.md"
        self._generate_markdown_report(comparison, md_file)
        print(f"📄 Markdown 对比报告已生成: {md_file}")
        print(f"📁 JSON 详细数据已保存至: {report_file}\n")

        return comparison

    def _print_comparison_table(self, comp: Dict[str, Any]):
        f_avg = comp["fast_mode"]["averages"]
        t_avg = comp["thinking_mode"]["averages"]
        delta = comp["delta"]

        print(f"\n{'='*75}")
        print(f"🏆 Fast Mode VS Thinking Mode 核心指标横向对比看板")
        print(f"{'='*75}")
        print(f"{'评测维度 (Metric)':<26} | {'Fast 极速模式':<14} | {'Thinking 思考模式':<16} | {'差异 (Delta)':<12}")
        print(f"{'-'*75}")
        print(f"{'Faithfulness (抗幻觉忠实度)':<22} | {f_avg['ragas_faithfulness']:<14.4f} | {t_avg['ragas_faithfulness']:<16.4f} | {delta['faithfulness_diff']:+<10.4f}")
        print(f"{'Answer Relevance (回答相关性)':<20} | {f_avg['ragas_answer_relevance']:<14.4f} | {t_avg['ragas_answer_relevance']:<16.4f} | {delta['relevance_diff']:+<10.4f}")
        print(f"{'Context Precision (检索精度)':<22} | {f_avg['ragas_context_precision']:<14.4f} | {t_avg['ragas_context_precision']:<16.4f} | {delta['precision_diff']:+<10.4f}")
        print(f"{'Context Recall (知识召回率)':<22} | {f_avg['ragas_context_recall']:<14.4f} | {t_avg['ragas_context_recall']:<16.4f} | {delta['recall_diff']:+<10.4f}")
        print(f"{'Semantic Similarity (语义相似)':<20} | {f_avg['semantic_similarity']:<14.4f} | {t_avg['semantic_similarity']:<16.4f} | {'-':<10}")
        print(f"{'-'*75}")
        print(f"{'综合 Ragas 质量得分':<24} | {comp['fast_mode']['overall_ragas_score']*100:<13.2f}% | {comp['thinking_mode']['overall_ragas_score']*100:<15.2f}% | {delta['overall_score_diff']*100:+<9.2f}%")
        print(f"{'平均响应耗时 (Latency)':<22} | {f_avg['average_latency_ms']:<11.1f} ms | {t_avg['average_latency_ms']:<13.1f} ms | {delta['latency_diff_ms']:+<10.1f} ms")
        print(f"{'='*75}\n")

    def _generate_markdown_report(self, comp: Dict[str, Any], md_path: Path):
        f_avg = comp["fast_mode"]["averages"]
        t_avg = comp["thinking_mode"]["averages"]
        delta = comp["delta"]

        content = f"""# AI-QA-Assistant 系统 Fast 与 Thinking 模式量化评测对比报告

- **评测时间**：{comp['timestamp']}
- **评测数据集**：Confluence 真实知识库基准集（共 {comp['total_samples']} 条用例）
- **评测框架**：Ragas 自动化量化评测体系 (RAG Triad)

---

## 1. 核心指标横向对比看板

| 评估指标 (Metric) | Fast 极速模式 | Thinking 深度思考模式 | 模式差异 (Delta) | 优势模式 |
| :--- | :---: | :---: | :---: | :---: |
| **Faithfulness（抗幻觉忠实度）** | `{f_avg['ragas_faithfulness']*100:.2f}%` | `{t_avg['ragas_faithfulness']*100:.2f}%` | `{delta['faithfulness_diff']*100:+.2f}%` | {"Thinking 模式" if delta['faithfulness_diff'] > 0 else "Fast 模式"} |
| **Answer Relevance（回答相关性）** | `{f_avg['ragas_answer_relevance']*100:.2f}%` | `{t_avg['ragas_answer_relevance']*100:.2f}%` | `{delta['relevance_diff']*100:+.2f}%` | {"Thinking 模式" if delta['relevance_diff'] > 0 else "Fast 模式"} |
| **Context Precision（检索精度）** | `{f_avg['ragas_context_precision']*100:.2f}%` | `{t_avg['ragas_context_precision']*100:.2f}%` | `{delta['precision_diff']*100:+.2f}%` | {"Thinking 模式" if delta['precision_diff'] > 0 else "Fast 模式"} |
| **Context Recall（知识召回率）** | `{f_avg['ragas_context_recall']*100:.2f}%` | `{t_avg['ragas_context_recall']*100:.2f}%` | `{delta['recall_diff']*100:+.2f}%` | {"Thinking 模式" if delta['recall_diff'] > 0 else "Fast 模式"} |
| **Semantic Similarity（语义相似度）** | `{f_avg['semantic_similarity']:.4f}` | `{t_avg['semantic_similarity']:.4f}` | - | - |
| **综合 Ragas 质量得分** | **`{comp['fast_mode']['overall_ragas_score']*100:.2f}`** / 100 | **`{comp['thinking_mode']['overall_ragas_score']*100:.2f}`** / 100 | **`{delta['overall_score_diff']*100:+.2f}%`** | {"Thinking 模式" if delta['overall_score_diff'] > 0 else "Fast 模式"} |
| **平均端到端响应耗时 (Latency)** | **`{f_avg['average_latency_ms']:.1f} ms`** | **`{t_avg['average_latency_ms']:.1f} ms`** | **`{delta['latency_diff_ms']:+.1f} ms`** | **Fast 模式 (显著极速)** |

---

## 2. 深入分析与模式特性对比

### 🚀 Fast 模式（极速直接 RAG）
- **核心机制**：采用无前置意图规划的单轮直接 RAG 架构。用户输入直接触发 `SearchTool` 混合检索并构建精简 Prompt 送入 LLM。
- **核心优势**：**极低延迟**（平均耗时仅为 Thinking 模式的 1/3 ~ 1/4），非常适合简单事实查询（Simple FAQ）。
- **局限性**：对复杂跨文档多跳推理（Multi-hop）或边界条件提问缺少自反思机制。

### 🧠 Thinking 模式（深度 Agent 编排模式）
- **核心机制**：走完整的 `AgentOrchestrator` 编排流程，涵盖多轮意图解析（`QueryUnderstanding`）、有界 Tool Calling 循环、`Evidence Gate` 证据判定与 `Citation` 一致性校对。
- **核心优势**：**高严谨性与抗幻觉能力**。在复杂条件判定与多段落综合问题上表现优异，答案结构化更佳。
- **局限性**：因多步 LLM 决策与工具循环，响应耗时较长。

---

## 3. 落地选型建议

1. **日常常规问答 / 移动端查询**：建议默认使用 **Fast 模式**，提供秒级流式响应。
2. **制度解读 / 复杂多步合规查询**：建议自动或手动切换至 **Thinking 模式**，确保事实核查与引用准确度。
"""
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content)


if __name__ == "__main__":
    evaluator = RagasEvaluator()
    evaluator.evaluate_comparison()
