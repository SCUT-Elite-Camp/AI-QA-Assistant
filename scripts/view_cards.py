"""知识卡片查看工具
用法: python scripts/view_cards.py
"""
import os, sys, sqlite3
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "data-pipeline"))
sys.path.insert(0, str(project_root / "data-persistence"))
sys.path.insert(0, str(project_root / "toolset"))

from pymilvus import connections, Collection, utility

def show_cards():
    connections.connect(host="localhost", port="19530")

    # List all collections
    print("=" * 60)
    print("  Milvus Collections")
    print("=" * 60)
    for name in utility.list_collections():
        coll = Collection(name)
        coll.load()
        print(f"  [{name}]  entities={coll.num_entities}")

    # Show knowledge_cards
    print()
    print("=" * 60)
    print("  Knowledge Cards (knowledge_cards)")
    print("=" * 60)
    coll = Collection("knowledge_cards")
    coll.load()
    results = coll.query(
        expr="id >= 0",
        output_fields=["chunk_id", "chunk_text", "doc_id"],
        limit=20,
    )

    for i, r in enumerate(results):
        cid = r["chunk_id"]
        lines = r["chunk_text"].split("\n")
        content = ""
        keywords = ""
        tags = ""
        context = ""
        for line in lines:
            if line.startswith("content: "):
                content = line[9:]
            elif line.startswith("keywords: "):
                keywords = line[10:]
            elif line.startswith("tags: "):
                tags = line[6:]
            elif line.startswith("context: "):
                context = line[9:]

        print(f"\n  [{i+1}] {cid}")
        print(f"      content:  {content[:100]}")
        print(f"      keywords: {keywords}")
        print(f"      tags:     {tags}")
        print(f"      context:  {context[:80]}")


def show_links():
    print()
    print("=" * 60)
    print("  Card Links (SQLite)")
    print("=" * 60)
    db_path = project_root / "data-persistence" / "data" / "card_links.db"
    if not db_path.exists():
        print("  No card_links.db found")
        return

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT source_id, target_id, link_type, strength, reason FROM card_links"
    ).fetchall()
    for r in rows:
        print(f"  {r[0][:30]}... --[{r[2]}]--> {r[1][:30]}...")
        print(f"    strength={r[3]}  reason: {r[4][:80]}")
    conn.close()

    # Graph stats
    conn = sqlite3.connect(str(db_path))
    nodes = set()
    for (s, t) in conn.execute("SELECT source_id, target_id FROM card_links").fetchall():
        nodes.add(s)
        nodes.add(t)
    links = conn.execute("SELECT count(*) FROM card_links").fetchone()[0]
    conn.close()
    print(f"\n  Graph: {len(nodes)} nodes, {links} edges")


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    show_cards()
    show_links()

    print()
    print("=" * 60)
    print("  产物位置")
    print("=" * 60)
    print(f"  Milvus:  localhost:19530  ->  knowledge_cards")
    print(f"  SQLite:  {project_root / 'data-persistence' / 'data' / 'card_links.db'}")
    print(f"  JSON:    {project_root / 'data-persistence' / 'data' / 'documents'}")
    print(f"  BM25:    {project_root / 'data-persistence' / 'data' / 'bm25_index.pkl'}")
