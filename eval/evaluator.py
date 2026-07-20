import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Setup python path to import project layers
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

# Load correct environment variables from agent/.env
from dotenv import load_dotenv
agent_env_path = project_root / "agent" / ".env"
if agent_env_path.exists():
    load_dotenv(dotenv_path=agent_env_path)

from eval.metrics import (
    calculate_hit_rate,
    calculate_mrr,
    calculate_map,
    calculate_rouge_l,
    calculate_bleu,
    calculate_semantic_similarity,
    evaluate_faithfulness,
    evaluate_answer_relevance
)


class SystemEvaluator:
    def __init__(self, questions_path: Optional[str] = None):
        if questions_path is None:
            self.questions_path = Path(__file__).parent / "eval_questions.json"
        else:
            self.questions_path = Path(questions_path)
            
        self.questions = self._load_questions()

    def _load_questions(self) -> List[Dict[str, Any]]:
        if not self.questions_path.exists():
            print(f"Warning: Test questions file not found at {self.questions_path}. Using a minimal default.")
            return [
                {
                    "id": 1,
                    "query": "公司实行的标准工作办公时间是怎样的？",
                    "expected_doc_ids": ["0af44b412ca78e9ee00d5e6ecaf080e0", "254ee6979979ed6cf4924694d91646d6"],
                    "ground_truth_answer": "每周5天、每日8小时标准工时制，周一至周五上午09:00—12:00，下午13:30—18:00。"
                }
            ]
        try:
            with open(self.questions_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading questions from {self.questions_path}: {e}")
            return []

    def evaluate_retrieval_performance(self, mode: str = "hybrid", top_k: int = 5) -> Dict[str, Any]:
        """Evaluates retrieval accuracy (Hit Rate, MRR, MAP) and latency"""
        print(f"\n>>> Running Retrieval Evaluation (Mode: {mode}, Top_K: {top_k})")
        from tool_layer.search_tool import SearchTool
        
        try:
            tool = SearchTool()
        except Exception as e:
            print(f"Error initializing SearchTool: {e}")
            return {"error": f"SearchTool initialization failed: {e}"}

        individual_results = []
        latencies = []
        hit_rates_1 = []
        hit_rates_3 = []
        hit_rates_5 = []
        mrrs = []
        maps = []

        for q in self.questions:
            query = q["query"]
            expected_doc_ids = q["expected_doc_ids"]

            start = time.perf_counter()
            try:
                search_results = tool.search(query=query, top_k=top_k, mode=mode)
                latency_ms = (time.perf_counter() - start) * 1000.0
                
                # Deduplicate retrieved document IDs to avoid inflation from multiple chunks of the same doc
                retrieved_doc_ids = []
                for item in search_results:
                    doc_id = item["doc_id"]
                    if doc_id not in retrieved_doc_ids:
                        retrieved_doc_ids.append(doc_id)
                
                hr_1 = calculate_hit_rate(retrieved_doc_ids, expected_doc_ids, 1)
                hr_3 = calculate_hit_rate(retrieved_doc_ids, expected_doc_ids, 3)
                hr_5 = calculate_hit_rate(retrieved_doc_ids, expected_doc_ids, 5)
                mrr = calculate_mrr(retrieved_doc_ids, expected_doc_ids, top_k)
                map_score = calculate_map(retrieved_doc_ids, expected_doc_ids, top_k)

                latencies.append(latency_ms)
                hit_rates_1.append(hr_1)
                hit_rates_3.append(hr_3)
                hit_rates_5.append(hr_5)
                mrrs.append(mrr)
                maps.append(map_score)

                individual_results.append({
                    "id": q["id"],
                    "query": query,
                    "expected": expected_doc_ids,
                    "retrieved": retrieved_doc_ids,
                    "hit_rate_1": hr_1,
                    "hit_rate_3": hr_3,
                    "hit_rate_5": hr_5,
                    "mrr": mrr,
                    "map": map_score,
                    "latency_ms": latency_ms,
                    "success": True
                })
            except Exception as e:
                print(f"  Error on query '{query}': {e}")
                individual_results.append({
                    "id": q["id"],
                    "query": query,
                    "expected": expected_doc_ids,
                    "error": str(e),
                    "success": False
                })

        # Calculate averages
        count = len(latencies)
        avg_latency = sum(latencies) / count if count > 0 else 0
        avg_hr_1 = sum(hit_rates_1) / count if count > 0 else 0
        avg_hr_3 = sum(hit_rates_3) / count if count > 0 else 0
        avg_hr_5 = sum(hit_rates_5) / count if count > 0 else 0
        avg_mrr = sum(mrrs) / count if count > 0 else 0
        avg_map = sum(maps) / count if count > 0 else 0

        summary = {
            "mode": mode,
            "top_k": top_k,
            "total_questions": len(self.questions),
            "successful_runs": count,
            "avg_latency_ms": avg_latency,
            "hit_rate_1": avg_hr_1,
            "hit_rate_3": avg_hr_3,
            "hit_rate_5": avg_hr_5,
            "mrr": avg_mrr,
            "map": avg_map
        }

        return {
            "summary": summary,
            "results": individual_results
        }

    def evaluate_generation_performance(self, mode: str = "hybrid", top_k: int = 5, use_judge: bool = False) -> Dict[str, Any]:
        """Evaluates end-to-end question answering latency and answer quality metrics"""
        print(f"\n>>> Running End-to-End Generation Evaluation (Retrieval Mode: {mode}, Top_K: {top_k}, Use LLM Judge: {use_judge})")
        from agent.agent import Agent
        from agent.schemas.chat import ChatRequest

        try:
            agent = Agent()
        except Exception as e:
            print(f"Error initializing Agent: {e}")
            return {"error": f"Agent initialization failed: {e}"}

        individual_results = []
        latencies = []
        bleu_scores = []
        rouge_scores = []
        semantic_similarities = []
        faithfulness_scores = []
        relevance_scores = []

        for q in self.questions:
            query = q["query"]
            ground_truth = q["ground_truth_answer"]

            start = time.perf_counter()
            try:
                req = ChatRequest(query=query, retrieval_mode=mode, top_k=top_k)
                resp = agent.chat(req)
                latency_ms = (time.perf_counter() - start) * 1000.0

                answer = resp.answer
                
                # Retrieve context strings for faithfulness evaluation
                context = ""
                if resp.citations:
                    context = "\n".join([f"[{i+1}] Title: {c.title}\nContent: {c.snippet or ''}" for i, c in enumerate(resp.citations)])
                elif hasattr(agent.tools.get("search_documents"), "latest_results"):
                    latest = agent.tools["search_documents"].latest_results
                    context = "\n".join([f"[{i+1}] Title: {item.get('title')}\nContent: {item.get('chunk_text')}" for i, item in enumerate(latest)])

                # Compute standard text metrics
                bleu = calculate_bleu(answer, ground_truth)
                rouge_l = calculate_rouge_l(answer, ground_truth)
                similarity = calculate_semantic_similarity(answer, ground_truth)

                latencies.append(latency_ms)
                bleu_scores.append(bleu)
                rouge_scores.append(rouge_l)
                semantic_similarities.append(similarity)

                result_entry = {
                    "id": q["id"],
                    "query": query,
                    "ground_truth": ground_truth,
                    "generated_answer": answer,
                    "status": resp.status,
                    "bleu": bleu,
                    "rouge_l": rouge_l,
                    "semantic_similarity": similarity,
                    "latency_ms": latency_ms,
                    "success": True
                }

                # Evaluate using LLM judge if enabled
                if use_judge:
                    f_eval = evaluate_faithfulness(answer, context)
                    r_eval = evaluate_answer_relevance(answer, query)
                    
                    faithfulness_scores.append(f_eval["score"])
                    relevance_scores.append(r_eval["score"])
                    
                    result_entry.update({
                        "faithfulness_score": f_eval["score"],
                        "faithfulness_reason": f_eval["reason"],
                        "relevance_score": r_eval["score"],
                        "relevance_reason": r_eval["reason"]
                    })

                individual_results.append(result_entry)
                print(f"  Processed Q{q['id']} ({resp.status}) - ROUGE-L: {rouge_l:.3f} | Similarity: {similarity:.3f} | Latency: {latency_ms:.1f}ms")
            except Exception as e:
                print(f"  Error on query '{query}': {e}")
                individual_results.append({
                    "id": q["id"],
                    "query": query,
                    "ground_truth": ground_truth,
                    "error": str(e),
                    "success": False
                })

        count = len(latencies)
        summary = {
            "total_questions": len(self.questions),
            "successful_runs": count,
            "avg_latency_ms": sum(latencies) / count if count > 0 else 0,
            "avg_bleu": sum(bleu_scores) / count if count > 0 else 0,
            "avg_rouge_l": sum(rouge_scores) / count if count > 0 else 0,
            "avg_semantic_similarity": sum(semantic_similarities) / count if count > 0 else 0
        }

        if use_judge and count > 0:
            summary.update({
                "avg_faithfulness": sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else 0,
                "avg_answer_relevance": sum(relevance_scores) / len(relevance_scores) if relevance_scores else 0
            })

        return {
            "summary": summary,
            "results": individual_results
        }

def format_summary_table(mode: str, data: Dict[str, Any]) -> str:
    """Helper to format evaluation summaries as nice console tables"""
    summary = data.get("summary", {})
    if not summary:
        return "No summary data to display."
        
    lines = []
    if mode == "retrieval":
        lines.append("=" * 60)
        lines.append(f"RETRIEVAL EVALUATION SUMMARY (Mode: {summary.get('mode')}, Top_K: {summary.get('top_k')})")
        lines.append("=" * 60)
        lines.append(f"Total Questions Evaluated:  {summary.get('total_questions')}")
        lines.append(f"Successful Runs:            {summary.get('successful_runs')}")
        lines.append(f"Average Latency:            {summary.get('avg_latency_ms'):.2f} ms")
        lines.append("-" * 60)
        lines.append(f"Hit Rate @ 1:               {summary.get('hit_rate_1') * 100:.1f} %")
        lines.append(f"Hit Rate @ 3:               {summary.get('hit_rate_3') * 100:.1f} %")
        lines.append(f"Hit Rate @ 5:               {summary.get('hit_rate_5') * 100:.1f} %")
        lines.append(f"Mean Reciprocal Rank (MRR): {summary.get('mrr'):.4f}")
        lines.append(f"Mean Average Precision(MAP):{summary.get('map'):.4f}")
        lines.append("=" * 60)
    elif mode == "generation":
        lines.append("=" * 60)
        lines.append("END-TO-END GENERATION EVALUATION SUMMARY")
        lines.append("=" * 60)
        lines.append(f"Total Questions Evaluated:  {summary.get('total_questions')}")
        lines.append(f"Successful Runs:            {summary.get('successful_runs')}")
        lines.append(f"Average Latency:            {summary.get('avg_latency_ms'):.2f} ms")
        lines.append("-" * 60)
        lines.append(f"Average BLEU Score:         {summary.get('avg_bleu'):.4f}")
        lines.append(f"Average ROUGE-L Score:      {summary.get('avg_rouge_l'):.4f}")
        lines.append(f"Average Semantic Similarity:{summary.get('avg_semantic_similarity'):.4f}")
        if "avg_faithfulness" in summary:
            lines.append(f"LLM-Judge Faithfulness (1-5): {summary.get('avg_faithfulness'):.2f} / 5")
            lines.append(f"LLM-Judge Answer Relevance (1-5): {summary.get('avg_answer_relevance'):.2f} / 5")
        lines.append("=" * 60)

    return "\n".join(lines)
