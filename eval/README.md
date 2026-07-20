# AI-QA-Assistant Performance Evaluation Module

This module is designed to test and measure the performance of the AI-QA-Assistant's core question-answering flow:
1. **Retrieval Performance** (Hit Rate, MRR, MAP, Latency)
2. **End-to-End Generation Quality** (ROUGE-L, BLEU, Semantic Similarity, and LLM-as-a-judge Faithfulness & Relevance)

---

## 1. Quick Start

Run the evaluation suite using the virtual environment's python interpreter:

```powershell
# Run all core evaluations (Retrieval and Generation)
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe eval/run_eval.py --mode all

# Run retrieval-only evaluation comparing vector, bm25, and hybrid modes
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe eval/run_eval.py --mode retrieval --retrieval-mode all_modes

# Run generation-only evaluation
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe eval/run_eval.py --mode generation

# Run generation evaluation with LLM judge enabled (requires a running LLM service)
$env:PYTHONUTF8=1; .\.venv\Scripts\python.exe eval/run_eval.py --mode generation --judge
```

---

## 2. Command Line Parameters

| Argument | Choices / Default | Description |
| --- | --- | --- |
| `--mode` | `all`, `retrieval`, `generation` (Default: `all`) | What component of the QA flow to evaluate. |
| `--retrieval-mode` | `vector`, `bm25`, `hybrid`, `all_modes` (Default: `hybrid`) | Retrieval algorithm to use during testing. |
| `--top-k` | Integer from 1 to 20 (Default: `5`) | Number of chunks retrieved per query. |
| `--judge` | Flag (Default: `False`) | Run LLM-as-a-judge faithfulness & relevance evaluation (requires running LLM). |
| `--output` | File path (Default: `eval_results.json`) | Filename/Path to save detailed evaluation records. |

---

## 3. Evaluation Metrics

### Retrieval Metrics
- **Hit Rate @ K** (K=1, 3, 5): Measures whether the correct source document ID is within the top-K retrieved results.
- **MRR (Mean Reciprocal Rank)**: Calculates the reciprocal of the rank of the first correct document.
- **MAP (Mean Average Precision)**: Measures precision considering the relative order of retrieved correct chunks.
- **Latency (ms)**: Time taken to search and rank chunks.

### Generation Metrics
- **BLEU-N**: Evaluates n-gram overlap between candidate and reference answers. Dynamically scales to short sentences.
- **ROUGE-L**: F1 score based on the Longest Common Subsequence (LCS) of Chinese tokens.
- **Semantic Similarity**: Cosine similarity of the SentenceTransformer embeddings of the candidate and ground truth answers.
- **LLM Judge - Faithfulness (1-5)**: Assesses whether the model answer is strictly grounded in the context (no hallucination).
- **LLM Judge - Answer Relevance (1-5)**: Assesses whether the model directly and comprehensively answers the query.

---

## 4. Benchmark Dataset

The questions used for evaluation are located in [eval_questions.json](file:///c:/Users/Hola/Desktop/Q&A/AI-QA-Assistant/eval/eval_questions.json). This file contains standard test questions, correct document identifiers, and ground truth answers mapped from the actual files in `测试数据` (测试空间).
