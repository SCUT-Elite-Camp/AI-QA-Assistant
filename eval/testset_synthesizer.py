import os
import sys
import json
import random
from pathlib import Path
from typing import List, Dict, Any

project_root = Path(__file__).resolve().parent.parent
for p in [str(project_root), str(project_root / "data-pipeline"), str(project_root / "data-persistence"), str(project_root / "agent")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from dotenv import load_dotenv
agent_env_path = project_root / "agent" / ".env"
if agent_env_path.exists():
    load_dotenv(dotenv_path=agent_env_path)


SYNTHESIZE_PROMPT = """你是一个 RAG 评测专家。请根据以下提供的企业真实知识库文档内容，自动生成 {num_questions} 道高质量测试问答题。

【知识库文档标题】：{title}
【知识库文档内容】：
{content}

【生成要求】：
生成 3 种不同难度的题型：
1. "simple"：基于单一知识块的事实型问答。
2. "multi_hop"：需要综合段落多个不同部分进行逻辑关联的推理型问答。
3. "condition"：带有假设条件或边界约束（如“如果/当...时”）的判定型问答。

【必须输出严格的 JSON 数组格式】：
[
  {{
    "id": "syn_001",
    "category": "simple",
    "question": "清晰具体的用户问题",
    "ground_truth": "直接且完整的标准参考答案",
    "expected_keywords": ["关键词1", "关键词2"]
  }}
]
"""

class TestsetSynthesizer:
    def __init__(self, doc_dir: Optional[str] = None):
        if doc_dir is None:
            self.doc_dir = project_root / "data-persistence" / "data" / "documents"
        else:
            self.doc_dir = Path(doc_dir)

    def load_documents(self) -> List[Dict[str, Any]]:
        docs = []
        if not self.doc_dir.exists():
            return docs
        for f in self.doc_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    if data.get("content") and len(data.get("content", "")) > 100:
                        docs.append(data)
            except Exception:
                continue
        return docs

    def synthesize(self, num_samples: int = 10, output_file: Optional[str] = None) -> List[Dict[str, Any]]:
        from agent.llm.llm_client import LLMClient
        import re

        docs = self.load_documents()
        if not docs:
            print(f"[WARN] No documents found in {self.doc_dir}")
            return []

        print(f"🔍 扫描到 {len(docs)} 篇本地知识库文档，准备自动合成 {num_samples} 道评测题目...")
        client = LLMClient()
        synthesized = []

        random.shuffle(docs)
        for doc in docs:
            if len(synthesized) >= num_samples:
                break

            title = doc.get("title", "未命名文档")
            content = doc.get("content", "")[:2500] # truncate for prompt

            prompt = SYNTHESIZE_PROMPT.format(num_questions=min(3, num_samples - len(synthesized)), title=title, content=content)
            try:
                raw_res = client.generate(prompt)
                match = re.search(r"\[.*\]", raw_res, re.DOTALL)
                if match:
                    items = json.loads(match.group(0))
                    for item in items:
                        item["source_doc"] = title
                        synthesized.append(item)
                        if len(synthesized) >= num_samples:
                            break
            except Exception as e:
                print(f"  [SKIP] 文档 '{title}' 合成失败: {e}")

        if output_file is None:
            output_file = project_root / "eval" / "confluence_synthesized_testset.json"
        else:
            output_file = Path(output_file)

        with open(output_file, "w", encoding="utf-8") as fp:
            json.dump(synthesized, fp, ensure_ascii=False, indent=2)

        print(f"✨ 成功合成 {len(synthesized)} 道评测集，保存至: {output_file}")
        return synthesized


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--num", type=int, default=8, help="Number of samples to synthesize")
    args = parser.parse_args()

    syn = TestsetSynthesizer()
    syn.synthesize(num_samples=args.num)
