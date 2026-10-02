# AI-QA-Assistant Performance Evaluation Module

## CP2 Agent evaluation

`run_agent_eval.py` tests the CP2 Agent layer separately from the existing
retrieval benchmark:

- **Components:** seven-intent accuracy, clarification precision/recall/F1,
  rewrite term retention, policy output, and Query Understanding latency.
- **Real quality:** real Qwen + local knowledge-base answers, required-fact
  coverage, citations, citation validity, stop reason, tool/retrieval counts,
  and end-to-end mean/P50/P90/P95 latency.

Retrieval Hit Rate, Recall, MRR, MAP, and retrieval-strategy comparisons remain
Tool Layer responsibilities and are intentionally excluded from this CP2 Agent
report.

The auditable dataset is `eval/datasets/agent_cp2_cases.json`. A required fact
is a synonym group, so wording may vary without hiding missing information.

All model-backed runs require explicit `--online` confirmation:

```powershell
D:\miniconda3\envs\htc_project\python.exe eval\run_agent_eval.py --suite components --online
D:\miniconda3\envs\htc_project\python.exe eval\run_agent_eval.py --suite quality --online
D:\miniconda3\envs\htc_project\python.exe eval\run_agent_eval.py --suite all --online --repeats 3
```

`--judge` adds relevance and faithfulness LLM-judge calls and therefore extra
API usage. Without it, real quality still uses deterministic fact and citation
metrics. Reports are JSON plus Excel-friendly UTF-8 CSV under `eval/reports/`.

### Local knowledge-base online test by complexity

`run_local_kb_online.py` runs real local-KB answer-quality tests while keeping
single-target questions separate from multi-aspect and compound questions.
Both groups use English questions. The legacy core-regression dataset remains
unchanged so historical reports stay reproducible.

```powershell
# Preview case IDs without calling an online model
D:\miniconda3\envs\htc_project\python.exe eval\run_local_kb_online.py --mode all --list

# Run ordinary single-target questions
D:\miniconda3\envs\htc_project\python.exe eval\run_local_kb_online.py --mode simple --online

# Run complex multi-aspect and compound questions
D:\miniconda3\envs\htc_project\python.exe eval\run_local_kb_online.py --mode complex --online

# Run both groups twice and choose the report path
D:\miniconda3\envs\htc_project\python.exe eval\run_local_kb_online.py --mode all --repeats 2 --online --output eval\reports\local_kb_online_all.json
```

The script writes one JSON report and a separate scalar CSV for each executed
group. It supports `--case-id`, `--limit`, `--judge`,
`--retrieval-namespace`, and `--no-retrieval-warmup`. `--mode ordinary` is an
alias of `--mode simple`.

Offline metric and dataset tests do not call an API:

```powershell
D:\miniconda3\envs\htc_project\python.exe -m pytest eval\test_agent_metrics.py -q
```

### FinanceBench real-finance baseline

The official FinanceBench corpus is kept locally under the gitignored
`eval/datasets/external/financebench/` directory. Generate the deterministic
20-case Agent manifest and collect only its required PDFs with:

```powershell
D:\miniconda3\envs\htc_project\python.exe eval\prepare_financebench.py
```

This creates the reviewable manifest
`eval/datasets/financebench_agent_cases.json` and copies the 20 source PDFs to
`eval/datasets/external/financebench_subset/pdfs/`. Ingest them into the
isolated `financebench_eval` namespace; this does not touch the default project
document directory, BM25 file, or Milvus collection:

```powershell
D:\miniconda3\envs\htc_project\python.exe eval\ingest_financebench.py
```

Then run answer-quality evaluation against the isolated namespace:

```powershell
D:\miniconda3\envs\htc_project\python.exe eval\run_agent_eval.py --suite quality --online --dataset eval\datasets\financebench_agent_cases.json --retrieval-namespace financebench_eval
```

Use `--limit 3` for a low-cost Agent smoke baseline before running all 20 cases.

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
