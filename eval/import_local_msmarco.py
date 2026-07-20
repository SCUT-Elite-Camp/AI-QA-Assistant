import argparse
import gzip
import json
import os
import sys
from pathlib import Path
import docx

# Setup paths to resolve imports correctly
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

from pipeline.process import process_folder
from storage.milvus_store import MilvusStore

def load_msmarco_file(file_path: str, max_items: int = 500):
    """Loads MS MARCO queries, passages, and answers from a local JSON/JSONL/GZ file.
    Supports both JSON and JSONL formats, gzip-compressed or raw text.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"MS MARCO data file not found: {file_path}")

    # Helper to open file (handles gzip dynamically)
    open_fn = gzip.open if path.suffix == ".gz" else open
    mode = "rt" if path.suffix == ".gz" else "r"

    items = []
    print(f"Reading MS MARCO file: {path.name}...")
    
    # Try reading as JSON
    try:
        with open_fn(file_path, mode, encoding="utf-8") as f:
            content = f.read().strip()
            # Try to parse as standard JSON
            data = json.loads(content)
            if isinstance(data, dict):
                # If QnA v2.1 dict format (query_id -> dict)
                for qid, val in data.items():
                    val["query_id"] = qid
                    items.append(val)
                    if len(items) >= max_items:
                        break
            elif isinstance(data, list):
                items = data[:max_items]
    except Exception:
        # Fallback to JSONL format
        items = []
        try:
            with open_fn(file_path, mode, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        val = json.loads(line)
                        items.append(val)
                        if len(items) >= max_items:
                            break
                    except Exception:
                        continue
        except Exception as e:
            raise ValueError(f"Failed to parse MS MARCO file as JSON or JSONL: {e}")

    print(f"Successfully loaded {len(items)} raw candidate entries from file.")
    return items

def main():
    parser = argparse.ArgumentParser(description="Import actual MS MARCO dataset into local RAG database")
    parser.add_argument("--file", type=str, required=True, help="Path to local dev_v2.1.json.gz or similar file")
    parser.add_argument("--num-queries", type=int, default=20, help="Number of queries to import (default: 20)")
    args = parser.parse_args()

    print("=" * 60)
    print("      IMPORTING MS MARCO DATASET LOCALLY      ")
    print("=" * 60)

    # 1. Load raw dataset entries
    try:
        raw_items = load_msmarco_file(args.file, max_items=args.num_queries * 10)
    except Exception as e:
        print(f"Error loading file: {e}")
        sys.exit(1)

    # Filter and extract valid QA pairs
    valid_qa_pairs = []
    for item in raw_items:
        query = item.get("query")
        passages = item.get("passages", [])
        answers = item.get("answers", [])
        
        # We need a query, standard answers, and at least one selected passage
        selected_passages = [p.get("passage_text") for p in passages if p.get("is_selected") == 1]
        all_passages = [p.get("passage_text") for p in passages if p.get("passage_text")]
        
        if query and answers and selected_passages and len(all_passages) >= 2:
            query_id = item.get("query_id") or item.get("query_id") or len(valid_qa_pairs) + 1
            valid_qa_pairs.append({
                "query_id": f"msmarco_q{query_id}",
                "query": query,
                "passages": all_passages,
                "answers": answers,
                "selected_passage": selected_passages[0]
            })
            if len(valid_qa_pairs) >= args.num_queries:
                break

    if not valid_qa_pairs:
        print("Error: Could not find any valid entries with standard answers and selected passages in the dataset.")
        sys.exit(1)

    print(f"Selected {len(valid_qa_pairs)} high-quality QA pairs for RAG evaluation.")

    # 2. Write passage .docx files
    raws_dir = project_root / "data-persistence" / "data" / "raws" / "ms_marco"
    # Clean up existing files in the directory to ensure a fresh index
    if raws_dir.exists():
        for f in raws_dir.glob("*.docx"):
            f.unlink()
        for f in raws_dir.glob("*.txt"):
            f.unlink()
    else:
        raws_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nWriting DOCX files to {raws_dir}...")
    for item in valid_qa_pairs:
        file_path = raws_dir / f"{item['query_id']}.docx"
        doc = docx.Document()
        # Add all passages to the document (relevant and irrelevant) as paragraphs
        for p in item["passages"]:
            doc.add_paragraph(p)
        doc.save(file_path)
        print(f"  Created document: {file_path.name}")

    from models.document import Document

    # 3. Create eval_questions_msmarco.json
    questions = []
    for idx, item in enumerate(valid_qa_pairs, start=1):
        file_path = raws_dir / f"{item['query_id']}.docx"
        abs_path = os.path.abspath(file_path)
        expected_hash = Document.generate_doc_id(abs_path)
        questions.append({
            "id": idx,
            "query": item["query"],
            "expected_doc_ids": [expected_hash],
            "ground_truth_answer": item["answers"][0]
        })

    questions_file = project_root / "eval" / "eval_questions_msmarco.json"
    with open(questions_file, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
    print(f"\nCreated evaluation questions file: {questions_file}")

    # 4. Clean up old documents under documents/
    docs_dir = project_root / "data-persistence" / "data" / "documents"
    if docs_dir.exists():
        for f in docs_dir.glob("*.json"):
            f.unlink()
            print(f"  Cleaned up old JSON document: {f.name}")

    # 5. Drop Milvus collection to prevent dimension mismatches (512 -> 384)
    print("\nResetting Milvus collection for English embedding dimensions...")
    try:
        milvus = MilvusStore()
        milvus.delete_collection("doc_chunks")
        print("Dropped Milvus collection successfully.")
    except Exception as e:
        print(f"Warning: Failed to drop Milvus collection: {e}")

    # 6. Run standard pipeline process on the new docx files
    print("\nRunning RAG parsing, chunking, and database indexing pipeline...")
    try:
        process_folder(str(raws_dir))
        print("\nMS MARCO dataset imported and RAG indexed successfully!")
    except Exception as e:
        print(f"Error running pipeline: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("      IMPORT AND RAG INDEXING COMPLETED!      ")
    print("=" * 60)

if __name__ == "__main__":
    main()
