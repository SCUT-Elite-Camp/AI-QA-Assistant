import os
import json

# 定义文档存放的默认目录（相对于工作目录）
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "documents")

def save_document(doc_id: str, data: dict) -> None:
    
    os.makedirs(DOCS_DIR, exist_ok=True)
    file_path = os.path.join(DOCS_DIR, f"{doc_id}.json")
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_document(doc_id: str) -> dict | None:
   
    file_path = os.path.join(DOCS_DIR, f"{doc_id}.json")
    
    if not os.path.exists(file_path):
        return None
        
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def delete_document(doc_id: str) -> None:
    
    file_path = os.path.join(DOCS_DIR, f"{doc_id}.json")
    
    if os.path.exists(file_path):
        os.remove(file_path)
