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

from models.document import Document

def main():
    print("=" * 60)
    print("      EXTRACTING & MERGING MS MARCO FOR EVALUATION      ")
    print("=" * 60)

    # 1. Load dev mappings (candidate pairs) from dev.tsv
    dev_tsv_path = project_root / "data-persistence" / "data" / "raws" / "ms_marco" / "dataset" / "msmarco" / "qrels" / "dev.tsv"
    if not dev_tsv_path.exists():
        print(f"Error: dev.tsv not found at {dev_tsv_path}")
        sys.exit(1)

    candidate_pairs = [] # List of tuples: (qid, cid)
    with open(dev_tsv_path, "r", encoding="utf-8") as f:
        header = f.readline() # query-id\tcorpus-id\tscore
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                qid, cid, score = parts[0], parts[1], parts[2]
                if score == "1":
                    candidate_pairs.append((qid, cid))
                    if len(candidate_pairs) >= 500: # Grab more to ensure we find 100 matches
                        break

    print(f"Loaded {len(candidate_pairs)} candidate positive pairs from dev.tsv.")

    # 2. Load query texts from queries.jsonl
    queries_path = project_root / "data-persistence" / "data" / "raws" / "ms_marco" / "dataset" / "msmarco" / "queries.jsonl"
    if not queries_path.exists():
        print(f"Error: queries.jsonl not found at {queries_path}")
        sys.exit(1)

    candidate_qids = set(p[0] for p in candidate_pairs)
    query_texts = {}
    with open(queries_path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            qid = data["_id"]
            if qid in candidate_qids:
                query_texts[qid] = data["text"]

    print(f"Loaded query texts for {len(query_texts)} queries.")

    # 3. Read corpus.jsonl to find positive passages and negative passages
    corpus_path = project_root / "data-persistence" / "data" / "raws" / "ms_marco" / "dataset" / "msmarco" / "corpus.jsonl"
    if not corpus_path.exists():
        print(f"Error: corpus.jsonl not found at {corpus_path}")
        sys.exit(1)

    candidate_cids = set(p[1] for p in candidate_pairs)
    positive_passage_texts = {}
    negative_passages = []
    needed_negatives = 99900 # 100,000 total passages minus 100 positive passages

    print("Scanning corpus.jsonl...")
    count = 0
    with open(corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            cid = data["_id"]
            text = data["text"]
            
            # If it is one of the candidate positive passages, store it
            if cid in candidate_cids:
                positive_passage_texts[cid] = text
            # Otherwise, use as negative passage (if we still need more)
            elif len(negative_passages) < needed_negatives:
                negative_passages.append(text)
            
            count += 1
            if count % 1000000 == 0:
                print(f"  Scanned {count} corpus passages...")

    print(f"Found {len(positive_passage_texts)} positive passage texts from corpus.")
    print(f"Collected {len(negative_passages)} negative passages.")

    # 4. Select exactly 100 valid QA pairs
    # A pair is valid if we have the query text and the positive passage text
    valid_qa_pairs = []
    for qid, cid in candidate_pairs:
        if qid in query_texts and cid in positive_passage_texts:
            valid_qa_pairs.append({
                "query": query_texts[qid],
                "positive_passage": positive_passage_texts[cid]
            })
            if len(valid_qa_pairs) >= 100:
                break

    if len(valid_qa_pairs) < 100:
        print(f"Error: Only found {len(valid_qa_pairs)} valid QA pairs. Need exactly 100.")
        sys.exit(1)

    print("Successfully selected 100 high-quality QA pairs.")

    # 5. Create output directory for docx documents
    raws_dir = project_root / "data-persistence" / "data" / "raws" / "ms_marco_evaluation"
    if raws_dir.exists():
        # Clear existing docx files to prevent pollution
        for f in raws_dir.glob("*.docx"):
            f.unlink()
    else:
        raws_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory prepared: {raws_dir}")

    # 6. Generate 500 docx files, each containing 200 paragraphs
    # Document 1 to 100 each contain 1 positive passage and 199 negative passages
    # Document 101 to 500 each contain 200 negative passages
    questions = []
    neg_idx = 0

    print("Generating DOCX documents...")
    for i in range(1, 501):
        doc_filename = f"msmarco_doc_{i:03d}.docx"
        file_path = raws_dir / doc_filename
        
        # Prepare the 200 paragraphs
        paragraphs = []
        is_positive_doc = (i <= 100)
        
        if is_positive_doc:
            # Add the positive passage first
            qa_pair = valid_qa_pairs[i - 1]
            paragraphs.append(qa_pair["positive_passage"])
            # Add 199 negatives
            paragraphs.extend(negative_passages[neg_idx : neg_idx + 199])
            neg_idx += 199
        else:
            # Add 200 negatives
            paragraphs.extend(negative_passages[neg_idx : neg_idx + 200])
            neg_idx += 200

        # Save to docx
        doc = docx.Document()
        for p_text in paragraphs:
            doc.add_paragraph(p_text)
        doc.save(file_path)

        # If it was a positive doc, add to the evaluation questions JSON list
        if is_positive_doc:
            qa_pair = valid_qa_pairs[i - 1]
            # Compute expected doc_id hash (absolute path hash)
            abs_path = os.path.abspath(file_path)
            expected_hash = Document.generate_doc_id(abs_path)
            
            questions.append({
                "id": i,
                "query": qa_pair["query"],
                "expected_doc_ids": [expected_hash],
                "ground_truth_answer": qa_pair["positive_passage"]
            })

    # 7. Write eval_questions_msmarco.json
    questions_file = project_root / "eval" / "eval_questions_msmarco.json"
    with open(questions_file, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)

    print(f"Generated 500 docx files at {raws_dir}")
    print(f"Generated evaluation questions at {questions_file}")
    print("=" * 60)
    print("      EXTRACTION AND MERGING COMPLETED!      ")
    print("=" * 60)

if __name__ == "__main__":
    main()
