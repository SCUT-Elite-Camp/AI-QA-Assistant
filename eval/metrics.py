import json
import math
import re
import sys
from pathlib import Path

# Add project roots to sys.path to ensure imports work
project_root = Path(__file__).resolve().parent.parent
for p in [str(project_root), str(project_root / "data-pipeline"), str(project_root / "data-persistence"), str(project_root / "agent")]:
    if p not in sys.path:
        sys.path.insert(0, p)

# --- 1. Retrieval Metrics ---

def calculate_hit_rate(retrieved_doc_ids: list[str], expected_doc_ids: list[str], k: int) -> float:
    """Calculates Hit Rate @ K (1.0 if any expected_doc_ids is in top-K retrieved docs, 0.0 otherwise)"""
    top_k_retrieved = retrieved_doc_ids[:k]
    for doc_id in expected_doc_ids:
        if doc_id in top_k_retrieved:
            return 1.0
    return 0.0


def calculate_mrr(retrieved_doc_ids: list[str], expected_doc_ids: list[str], k: int) -> float:
    """Calculates Mean Reciprocal Rank @ K (1 / rank of the first correct retrieved doc, or 0.0 if not in top-K)"""
    for rank, doc_id in enumerate(retrieved_doc_ids[:k], 1):
        if doc_id in expected_doc_ids:
            return 1.0 / rank
    return 0.0


def calculate_map(retrieved_doc_ids: list[str], expected_doc_ids: list[str], k: int) -> float:
    """Calculates Average Precision @ K (AP@K) for a single query"""
    hits = 0
    sum_precisions = 0.0
    for rank, doc_id in enumerate(retrieved_doc_ids[:k], 1):
        if doc_id in expected_doc_ids:
            hits += 1
            sum_precisions += hits / rank
    if hits == 0:
        return 0.0
    return sum_precisions / min(len(expected_doc_ids), k)


# --- 2. Generation Metrics ---

def _lcs(x: list, y: list) -> int:
    """Computes the Longest Common Subsequence of two sequences"""
    n, m = len(x), len(y)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if x[i - 1] == y[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[n][m]


def calculate_rouge_l(candidate: str, reference: str) -> float:
    """Calculates token-level ROUGE-L (F1 score based on LCS) using jieba for tokenization"""
    if not candidate or not reference:
        return 0.0

    import jieba
    try:
        # Disable logging for jieba
        import logging
        jieba.setLogLevel(logging.WARNING)
        cand_tokens = list(jieba.cut(candidate.strip()))
        ref_tokens = list(jieba.cut(reference.strip()))
    except Exception:
        cand_tokens = list(candidate.strip())
        ref_tokens = list(reference.strip())

    if not cand_tokens or not ref_tokens:
        return 0.0

    lcs_len = _lcs(cand_tokens, ref_tokens)
    prec = lcs_len / len(cand_tokens)
    rec = lcs_len / len(ref_tokens)
    if prec + rec == 0:
        return 0.0
    return (2 * prec * rec) / (prec + rec)


def calculate_bleu(candidate: str, reference: str, max_n: int = 4) -> float:
    """Calculates n-gram BLEU score with brevity penalty and smoothing, adapting to short sentences"""
    if not candidate or not reference:
        return 0.0

    import jieba
    from collections import Counter
    try:
        import logging
        jieba.setLogLevel(logging.WARNING)
        cand_tokens = list(jieba.cut(candidate.strip()))
        ref_tokens = list(jieba.cut(reference.strip()))
    except Exception:
        cand_tokens = list(candidate.strip())
        ref_tokens = list(reference.strip())

    if not cand_tokens or not ref_tokens:
        return 0.0

    # Adapt max_n based on the actual token count
    actual_max_n = min(max_n, len(cand_tokens), len(ref_tokens))
    if actual_max_n == 0:
        return 0.0

    # Brevity penalty
    c_len = len(cand_tokens)
    r_len = len(ref_tokens)
    if c_len > r_len:
        bp = 1.0
    else:
        bp = math.exp(1 - r_len / c_len) if c_len > 0 else 0.0

    p_ns = []
    for n in range(1, actual_max_n + 1):
        cand_ngrams = [tuple(cand_tokens[i:i+n]) for i in range(len(cand_tokens) - n + 1)]
        ref_ngrams = [tuple(ref_tokens[i:i+n]) for i in range(len(ref_tokens) - n + 1)]

        cand_counts = Counter(cand_ngrams)
        ref_counts = Counter(ref_ngrams)

        clipped_count = 0
        for ngram, count in cand_counts.items():
            clipped_count += min(count, ref_counts.get(ngram, 0))

        p_n = clipped_count / len(cand_ngrams)
        p_ns.append(p_n)

    # Smoothing
    smoothed_p_ns = []
    for p in p_ns:
        if p == 0:
            smoothed_p_ns.append(1e-9)
        else:
            smoothed_p_ns.append(p)

    weights = [1.0 / actual_max_n] * actual_max_n
    s = sum(w * math.log(p) for w, p in zip(weights, smoothed_p_ns))
    return bp * math.exp(s)


def calculate_semantic_similarity(candidate: str, reference: str) -> float:
    """Calculates semantic similarity using SentenceTransformers (BGE model via pipeline.embedder)"""
    if not candidate or not reference:
        return 0.0

    from pipeline.embedder import embed_texts
    try:
        embeddings = embed_texts([candidate, reference])
        if len(embeddings) < 2:
            return 0.0
        vec1, vec2 = embeddings[0], embeddings[1]

        # Cosine similarity
        dot = sum(a * b for a, b in zip(vec1, vec2))
        mag1 = math.sqrt(sum(a * a for a in vec1))
        mag2 = math.sqrt(sum(b * b for b in vec2))

        if mag1 * mag2 == 0:
            return 0.0
        return dot / (mag1 * mag2)
    except Exception as e:
        # Fallback print or log
        return 0.0


# --- 3. LLM-as-a-Judge Evaluation ---

FAITHFULNESS_PROMPT = """
你是一个客观的问答评估专家。你需要评估AI生成的回答是否“忠实于”给定的参考上下文，即是否存在与上下文矛盾、凭空编造事实或推测的内容。

【参考上下文】：
{context}

【AI生成的回答】：
{answer}

请根据以下标准进行打分，给出 1 到 5 的整数评分，并且必须使用 JSON 格式返回，格式为：
{{"score": 整数评分, "reason": "你的简要评估理由"}}

打分标准：
5 分：完全忠实。回答中的所有事实在上下文中都有明确依据，没有任何编造或超出上下文范畴的常识性猜测。
4 分：高度忠实。绝大部分内容有依据，仅有极其微小的表述或修饰性词语无法从上下文中直接找到，但未歪曲上下文事实。
3 分：中度忠实。主要事实符合上下文，但包含少量未提及的细节或常识性推测。
2 分：低度忠实。包含了明显在上下文中未提及的编造内容或推论，或者曲解了部分上下文内容。
1 分：完全不忠实。回答充斥着与上下文矛盾的信息，或者完全属于大模型根据自身知识凭空编造的内容。
"""

ANSWER_RELEVANCE_PROMPT = """
你是一个客观的问答评估专家。你需要评估AI生成的回答是否“切题”，即是否直接、完整地回答了用户提出的问题。

【用户问题】：
{query}

【AI生成的回答】：
{answer}

请根据以下标准进行打分，给出 1 到 5 的整数评分，并且必须使用 JSON 格式返回，格式为：
{{"score": 整数评分, "reason": "你的简要评估理由"}}

打分标准：
5 分：完美切题。答案直接回答了问题，内容全面，没有废话或跑题内容。
4 分：高度切题。直接回答了问题，但可能在全面性上略有欠缺，或者包含少量无关轻重的延伸信息。
3 分：中度切题。虽然回答了问题，但表述较为间接，或者参杂了较多与原问题无关的信息。
2 分：低度切题。只回答了问题的极小部分，或者大篇幅跑题。
1 分：完全不切题。答非所问，没有提供任何有用的信息，或者根本没有回答问题。
"""


def call_llm_judge(prompt: str) -> dict:
    """Calls the system's LLM Client to score a prompt, parsing JSON output"""
    from agent.llm.llm_client import LLMClient
    
    try:
        client = LLMClient()
        response_text = client.generate(prompt)

        
        # Extract JSON substring
        match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        else:
            # Try to search for "score": \d
            score_match = re.search(r'"score"\s*:\s*(\d)', response_text)
            reason_match = re.search(r'"reason"\s*:\s*"([^"]*)"', response_text)
            score = int(score_match.group(1)) if score_match else 4
            reason = reason_match.group(1) if reason_match else "Extracted from plain text response."
            return {"score": score, "reason": reason}
    except Exception as e:
        return {"score": 3, "reason": f"LLM judge failed to request or parse: {e}"}


def evaluate_faithfulness(answer: str, context: str) -> dict:
    """Scores answer faithfulness to the context from 1 to 5"""
    if not answer or not context:
        return {"score": 1, "reason": "Empty answer or context."}
    prompt = FAITHFULNESS_PROMPT.format(context=context, answer=answer)
    return call_llm_judge(prompt)


def evaluate_answer_relevance(answer: str, query: str) -> dict:
    """Scores answer relevance to the query from 1 to 5"""
    if not answer or not query:
        return {"score": 1, "reason": "Empty answer or query."}
    prompt = ANSWER_RELEVANCE_PROMPT.format(query=query, answer=answer)
    return call_llm_judge(prompt)
