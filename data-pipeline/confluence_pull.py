"""
Confluence 空间连接器（Stream 直连模式）。

功能：
  1. 用 Basic Auth（邮箱 + API Token）访问 Confluence Cloud REST API。
  2. 递归拉取指定空间（默认 test）下的全部页面。
  3. **Stream 直连**：API 返回 HTML → HtmlParser.parse_string() → Document
     → 直接喂给切片/嵌入/入库管道，**完全不落盘中间文件**。
  4. 每个页面输出统一 Document 模型，metadata 含：
     - source_url       页面完整访问链接
     - space_key        页面所属空间 Key
     - page_id          页面 ID
     - title            页面标题
     - version          版本号
     - last_updated     最后更新时间（ISO）
     - has_attachment   是否含附件
     - attachment_names 附件文件名列表
     - content_type     html / attachment / hybrid
     - attachments_processed 每个附件处理详情
  5. 汇总写出 ``confluence_metadata_<space>.json`` 供权限管理与来源追溯。

用法：
    python confluence_pull.py [space_key]
"""

import os
import sys
import json
import time
import logging

import requests

# 将相关目录加入 sys.path，以便导入 parsers / models / pipeline / storage
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)  # AI-QA-Assistant
DATA_PERSISTENCE = os.path.join(REPO, "data-persistence")
for p in (HERE, REPO, DATA_PERSISTENCE):
    if p not in sys.path:
        sys.path.insert(0, p)

# 修复 Windows 控制台 GBK 编码问题（避免 emoji/特殊字符打印崩溃）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ENV_PATH = os.path.join(HERE, ".confluence.env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("confluence_pull")


# ───────────────────────────── 配置加载 ─────────────────────────────

def load_creds() -> dict:
    """从 .confluence.env 加载 Confluence API 凭据"""
    creds: dict = {}
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip().strip('"').strip("'")
    return {
        "base": creds["CONFLUENCE_BASE"],
        "email": creds["CONFLUENCE_EMAIL"],
        "token": creds["CONFLUENCE_TOKEN"],
    }


# ───────────────────────────── API 封装 ─────────────────────────────

def api_get(session: requests.Session, base: str, path: str, params=None, tries: int = 5):
    """Confluence API GET 请求（带限流重试）"""
    url = base + path
    for attempt in range(tries):
        r = session.get(url, params=params, timeout=30)
        if r.status_code == 429:
            wait = 2 ** attempt
            logger.warning(f"触发限流(429)，{wait}s 后重试...")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Confluence API 多次限流，已放弃")


def get_all_pages(session: requests.Session, base: str, space: str) -> list:
    """分页获取空间下所有页面"""
    pages: list = []
    start = 0
    limit = 50
    while True:
        data = api_get(
            session, base, "/rest/api/content",
            {"spaceKey": space, "type": "page", "start": start,
             "limit": limit, "expand": "version,history"},
        )
        results = data.get("results", [])
        if not results:
            break
        pages.extend(results)
        total = data.get("size", 0)
        if start + limit >= total:
            break
        start += limit
        time.sleep(0.2)
    return pages


# ───────────────────────────── 管道接入 ─────────────────────────────

def _run_pipeline(doc) -> None:
    """将单个 Document 送入后续处理管道：切片 → 向量化 → 保存 JSON → 写入 Milvus

    此函数复用 process.py 的管道逻辑，确保 Confluence 来源文档与本地文件
    走完全相同的下游路径。
    """
    from models.document import Document
    from pipeline.chunker import chunk_from_blocks, chunk_text
    from pipeline.embedder import embed_texts
    from storage.document_store import save_document
    from storage.milvus_store import MilvusStore

    # 1. 切片
    if doc.content_blocks:
        chunks = chunk_from_blocks(
            doc.content_blocks, doc.doc_id, chunk_size=500, overlap=100
        )
    else:
        chunks = chunk_text(doc.content, doc.doc_id, chunk_size=500, overlap=100)
    doc.chunks = chunks
    logger.info(f"  切片完成: {len(chunks)} 个分块")

    if not chunks:
        logger.warning(f"  跳过（无内容）")
        return

    # 2. 向量化
    chunk_texts = [ch.text for ch in chunks]
    logger.info(f"  正在向量化 {len(chunk_texts)} 个分块...")
    embeddings = embed_texts(chunk_texts)
    logger.info(f"  向量化完成")

    # 3. 保存 JSON
    json_data = doc.model_dump(mode="json")
    save_document(doc.doc_id, json_data)
    logger.info(f"  JSON 已保存: documents/{doc.doc_id}.json")

    # 4. 写入 Milvus
    milvus = MilvusStore(host="localhost", port="19530")
    chunk_ids = [ch.chunk_id for ch in chunks]
    doc_ids = [doc.doc_id] * len(chunks)
    chunk_indices = [ch.index for ch in chunks]
    source_urls = [doc.source_url] * len(chunks)
    milvus.insert_chunks(
        embeddings=embeddings,
        chunk_ids=chunk_ids,
        chunk_texts=chunk_texts,
        doc_ids=doc_ids,
        chunk_indices=chunk_indices,
        source_urls=source_urls,
    )
    logger.info(f"  向量已写入 Milvus")


# ───────────────────────────── 主流程 ─────────────────────────────

def main() -> None:
    # 参数解析：confluence_pull.py [space] [--pages id1,id2,...]
    args = sys.argv[1:]
    space = "test"
    only_pages = None
    rest = []
    for a in args:
        if a.startswith("--pages="):
            only_pages = a.split("=", 1)[1].split(",")
        elif a.startswith("--"):
            pass  # 忽略未知 flag
        else:
            rest.append(a)
    if rest:
        space = rest[0]

    creds = load_creds()
    base = creds["base"]
    domain = base.split("/wiki")[0]

    session = requests.Session()
    session.auth = (creds["email"], creds["token"])
    session.headers.update({"Accept": "application/json"})

    print(f"\n{'='*60}")
    print(f"开始抓取 Confluence 空间: {space}  (base={base})")
    print(f"模式: Stream 直连 (HTML → HtmlParser → Document → 管道)")
    if only_pages:
        print(f"仅重跑指定页面: {only_pages}")
    print(f"{'='*60}\n")

    if only_pages:
        pages = [{"id": pid, "title": f"(page {pid})"} for pid in only_pages]
    else:
        pages = get_all_pages(session, base, space)
    print(f"空间 {space} 共发现 {len(pages)} 个页面\n")

    metas: list = []
    success_count = 0

    for idx, pg in enumerate(pages, 1):
        pid = pg["id"]
        title = pg["title"]
        print(f"[{idx}/{len(pages)}] 处理: {title} (id={pid})")

        try:
            # 1. 获取页面详情（含 HTML 正文）
            detail = api_get(
                session, base, f"/rest/api/content/{pid}",
                {"expand": "body.view,version,history"},
            )
            body_html = detail.get("body", {}).get("view", {}).get("value", "")
            version = detail.get("version", {}).get("number")
            last_updated = (
                detail.get("version", {}).get("when")
                or detail.get("history", {}).get("lastUpdated", {}).get("when", "")
            )
            webui = (
                detail.get("_links", {}).get("webui")
                or pg.get("_links", {}).get("webui")
            )
            source_url = (domain + webui) if webui else f"{domain}/wiki/pages/{pid}"

            # 2. ★ Stream 直连：HtmlParser.parse_string() 直接解析 HTML → [主文档, *附件文档]
            from parsers.html_parser import HtmlParser
            docs = HtmlParser.parse_string(
                html_string=body_html,
                source_url=source_url,
                title=title,
                space_key=space,
                page_id=pid,
                last_updated=last_updated,
                api_creds=creds,  # 传入凭据以启用附件下载
            )

            # 3. ★ 逐个文档送入管道（一附件一文档，不落盘任何中间文件）
            for d in docs:
                ctype = d.metadata.get("content_type", "?")
                print(f"  → 文档[{ctype}]: {d.title} "
                      f"({len(d.content)} 字符, {len(d.content_blocks)} 块, id={d.doc_id[:8]})")
                _run_pipeline(d)

                # 4. 记录元数据（主文档与附件文档各一行，便于溯源）
                metas.append({
                    "source_url": d.source_url,
                    "space_key": space,
                    "page_id": pid,
                    "title": d.title,
                    "version": version if ctype != "attachment" else None,
                    "last_updated": d.last_updated,
                    "has_attachment": ctype == "attachment",
                    "attachment_names": [d.metadata.get("filename", "")] if ctype == "attachment" else [],
                    "content_type": ctype,
                    "doc_id": d.doc_id,
                    "parent_page_id": d.metadata.get("parent_page_id", ""),
                })

            success_count += 1

        except Exception as e:
            print(f"  [FAIL] 处理失败: {e}")
            import traceback
            traceback.print_exc()
            # 也记录失败的元数据
            metas.append({
                "source_url": "", "space_key": space, "page_id": pid,
                "title": title, "version": None, "last_updated": "",
                "has_attachment": False, "attachment_names": [],
                "content_type": "error", "doc_id": "",
                "error": str(e),
            })

        time.sleep(0.3)

    # ═══ 汇总元数据 ═══
    meta_path = os.path.join(HERE, f"confluence_metadata_{space}.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "space_key": space,
                "base": base,
                "total": len(pages),
                "success": success_count,
                "failed": len(pages) - success_count,
                "pages": metas,
            },
            f, ensure_ascii=False, indent=2,
        )

    print(f"\n{'='*60}")
    print(f"[OK] 完成！成功处理 {success_count}/{len(pages)} 个页面")
    print(f"   元数据汇总: {meta_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
