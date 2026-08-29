"""
HTML 解析器：解析 Confluence API 返回的 HTML 页面（含附件），输出统一 Document 模型。

支持两种入口:
  - parse(file_path):        从磁盘 .html 文件解析（Batch 模式，兼容 process.py 扫描）
  - parse_string(html, ...): 从内存 HTML 字符串直接解析（Stream 模式，Confluence 直连）

三步处理逻辑:
  第一步: 页面类型判断
    - html_string 包含大量可见文字 → "html" 分支（HTML 正文解析）
    - html_string 为空或仅含 <ac:link>/<ri:attachment> → "attachment" 分支（仅附件）
    - 同时包含正文和附件引用 → "hybrid" 分支（两者都走，最后合并）

  第二步: HTML 正文解析
    - BeautifulSoup 解析 <body>
    - 保留核心标签: <p> / <h1>-<h6> / <li> / <td> / <table> 等
    - 处理 Confluence 特有宏: <ac:structured-macro> 提取文本并加标记
    - 保持阅读顺序

  第三步: 附件下载与解析
    - 调 Confluence API 列出/下载附件
    - 根据文件类型分发到对应解析器 (.pptx/.docx/.pdf/.xlsx)
    - 合并附件文本并加 [Attachment: filename] 标记
    - 解析后清理临时文件
"""

import logging
import os
import re
import shutil
import tempfile
from typing import Any

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

from models.document import Document, ContentBlock, BlockType
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

# ── Confluence 宏标记前缀 ──
_MACRO_PREFIXES: dict[str, str] = {
    "code": "[CodeBlock",
    "info": "[Info",
    "note": "[Note",
    "warning": "[Warning",
    "panel": "[Panel",
    "expand": "[Expand",
    "status": "[Status",
    "jira": "[JIRA",
    "toc": "[TOC",
}

# ── 附件类型 → 解析器映射 ─_
_ATTACHMENT_PARSERS: dict[str, str] = {
    ".pptx": "parsers.pptx_parser.PptxParser",
    ".docx": "parsers.docx_parser.DocxParser",
    ".pdf": "parsers.pdf_parser.PDFParser",
    ".xlsx": "parsers.xlsx_parser.XlsxParser",
}


class HtmlParser(BaseParser):
    """解析 Confluence HTML 页面（含附件），输出统一 Document 对象"""

    # ─────────────────────── 公共接口 ───────────────────────

    def parse(self, file_path: str) -> list[Document]:
        """从磁盘 .html 文件解析（Batch 模式，process.py 调用）

        返回 list[Document]：可能包含 1 个主文档 + N 个附件独立文档。
        """
        with open(file_path, encoding="utf-8") as f:
            html_string = f.read()

        # 尝试加载同目录的侧车元数据（如果存在）
        meta = self._load_sidecar(file_path)

        return self._parse_html(
            html_string=html_string,
            source=file_path,
            metadata=meta,
            api_creds=None,  # Batch 模式不调 API 下载附件（附件应已提前下载到 _attachments/）
        )

    @classmethod
    def parse_string(
        cls,
        html_string: str,
        source_url: str = "",
        title: str = "",
        space_key: str = "",
        page_id: str = "",
        last_updated: str = "",
        metadata: dict | None = None,
        api_creds: dict | None = None,
    ) -> list[Document]:
        """从内存 HTML 字符串直接解析（Stream 模式，confluence_pull.py 调用）

        返回 list[Document]：
          - 第 0 个为主文档（页面正文，可能为空壳），content_type=html/hybrid/attachment
          - 后续每个成功解析的附件各占一个独立 Document，
            title=文件名，content_type="attachment"，metadata 含 parent_page_id/attachment_id

        Args:
            html_string: Confluence API 返回的 body.view.value (HTML)
            source_url:   页面完整访问链接
            title:        页面标题
            space_key:    空间 Key
            page_id:      页面 ID
            last_updated: 最后更新时间 (ISO)
            metadata:     额外元数据字典
            api_creds:    Confluence API 凭据 {"base", "email", "token"}，
                          传入时启用附件下载；为 None 则跳过附件处理
        """
        meta = dict(metadata or {})
        meta.update({
            "source_url": source_url or meta.get("source_url", ""),
            "space_key": space_key or meta.get("space_key", ""),
            "page_id": page_id or meta.get("page_id", ""),
            "last_updated": last_updated or meta.get("last_updated", ""),
        })

        parser = cls()
        return parser._parse_html(
            html_string=html_string,
            source=source_url or f"confluence:{page_id}",
            metadata=meta,
            api_creds=api_creds,
        )

    # ─────────────────────── 核心三步处理 ───────────────────────

    def _parse_html(
        self,
        html_string: str,
        source: str,
        metadata: dict,
        api_creds: dict | None = None,
    ) -> list[Document]:
        """核心解析入口：三步处理 → 返回 [主文档, *附件独立文档]

        设计原则：页面正文与每个附件各自成为独立的 Document，
        保证一附件一 JSON，便于检索归属、溯源与增量更新。
        """
        page_id = metadata.get("page_id", "")

        # ═══ 第一步：页面类型判断 ═══
        page_type = self._classify_page(html_string)
        logger.info(f"页面类型判定: {page_type} (source={source})")

        # ═══ 第二步：HTML 正文解析（主文档内容）═══
        main_blocks: list[ContentBlock] = []
        if page_type in ("html", "hybrid"):
            main_blocks = self._parse_body(html_string)
            logger.info(f"HTML 正文解析: {len(main_blocks)} 个内容块")

        # ═══ 第三步：附件下载与解析（每个附件独立文档）═══
        attachment_docs: list[Document] = []
        attachments_processed: list[dict] = []
        if page_type in ("attachment", "hybrid") and api_creds:
            att_creds = dict(api_creds)
            att_creds["space_key"] = metadata.get("space_key", "")
            attachment_docs, attachments_processed = self._process_attachments(
                page_id=page_id,
                creds=att_creds,
            )
        elif page_type in ("attachment", "hybrid") and not api_creds:
            # 无 API 凭据时尝试从本地 _attachments/ 目录读取
            attachment_docs, attachments_processed = self._load_local_attachments(source)

        # ═══ 组装主文档元数据 ═══
        has_attachment = bool(attachments_processed)
        attachment_names = [
            ap["filename"] for ap in attachments_processed if ap.get("success")
        ]
        main_meta = dict(metadata)
        main_meta.update({
            "has_attachment": has_attachment,
            "attachment_names": attachment_names,
            "content_type": page_type,
            "attachments_processed": attachments_processed,
            "is_attachment_parent": bool(attachment_docs),
        })

        # ═══ 构建主文档（始终存在，作为页面级索引）═══
        main_doc = self._build_document(
            source=source,
            blocks=main_blocks,
            metadata=main_meta,
            page_id=page_id,
            title=metadata.get("title"),
        )

        # ═══ 返回：主文档 + 所有附件独立文档 ═══
        return [main_doc, *attachment_docs]

    def _build_document(
        self,
        source: str,
        blocks: list[ContentBlock],
        metadata: dict,
        page_id: str = "",
        title: str | None = None,
    ) -> Document:
        """从 blocks + metadata 构建统一 Document（含 doc_id 生成）"""
        content = "\n\n".join(
            cb.to_markdown() for cb in blocks if not cb.is_empty
        )
        content = self._clean_text(content)

        doc_id = self._generate_doc_id(source, page_id)
        doc_title = (
            title
            or metadata.get("title")
            or os.path.splitext(os.path.basename(source))[0]
        )
        space = metadata.get("space_key", "confluence")
        address = source
        last_updated = metadata.get("last_updated", "")
        source_url = metadata.get("source_url", "")

        return Document(
            doc_id=doc_id,
            title=doc_title,
            content=content,
            space=space,
            address=address,
            last_updated=last_updated,
            source_url=source_url,
            content_blocks=blocks,
            metadata=metadata,
        )

    # ════════════════════ 第一步：页面类型判断 ════════════════════

    @staticmethod
    def _classify_page(html_string: str) -> str:
        """判断页面类型: html / attachment / hybrid

        规则:
        - html:       HTML 含大量可见文字（非纯标签）
        - attachment: HTML 为空 或 仅含 <ac:link>/<ri:attachment> 等引用标签
        - hybrid:     同时包含正文文字和附件引用
        """
        if not html_string or not html_string.strip():
            return "attachment"

        soup = BeautifulSoup(html_string, "html.parser")

        # 移除 script/style 等不可见元素
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        # 提取所有可见文本
        visible_text = soup.get_text(separator=" ", strip=True)
        visible_text = re.sub(r"\s+", " ", visible_text).strip()

        # 检测是否存在 Confluence 附件引用标签
        has_attachment_refs = bool(
            soup.find_all("ri:attachment") or
            soup.find_all(attrs={"ri:attachment": True}) or
            re.search(r"ri:attachment|ac:link.*attachment", html_string)
        )

        has_visible_content = len(visible_text) > 20  # 阈值：超过 20 字符视为有正文

        if has_visible_content and has_attachment_refs:
            return "hybrid"
        elif has_visible_content:
            return "html"
        else:
            return "attachment"

    # ════════════════════ 第二步：HTML 正文解析 ════════════════════

    def _parse_body(self, html_string: str) -> list[ContentBlock]:
        """使用 BeautifulSoup 解析 HTML 正文，输出 ContentBlock 列表

        处理规则:
        - <h1>-<h6> → HEADING
        - <p>        → PARAGRAPH
        - <li>       → LIST
        - <table>    → TABLE
        - <ac:structured-macro> → 带标记的 PARAGRAPH（如 [Status: 已完成]）
        - 保持阅读顺序
        """
        soup = BeautifulSoup(html_string, "html.parser")

        # 移除不可见元素
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        # 只处理 <body> 内容，如果没有 body 则用整个文档
        body = soup.find("body") or soup

        blocks: list[ContentBlock] = []
        self._walk_node(body, blocks)
        return blocks

    def _walk_node(self, node: Any, blocks: list[ContentBlock]) -> None:
        """递归遍历 DOM 节点，按阅读顺序提取内容块"""
        for child in node.children:
            if not isinstance(child, Tag):
                continue

            name = child.name

            # ── 标题 ──
            if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                level = min(int(name[1]), 6)
                text = child.get_text(strip=True)
                if text:
                    blocks.append(ContentBlock(
                        block_type=BlockType.HEADING,
                        text=text,
                        level=level,
                    ))

            # ── 段落 ──
            elif name == "p":
                text = child.get_text(strip=True)
                if text:
                    is_bold = bool(child.find("b")) or bool(child.find("strong"))
                    is_italic = bool(child.find("i")) or bool(child.find("em"))
                    blocks.append(ContentBlock(
                        block_type=BlockType.PARAGRAPH,
                        text=text,
                        bold=is_bold,
                        italic=is_italic,
                    ))

            # ── 列表项 ──
            elif name == "li":
                text = child.get_text(strip=True)
                if text:
                    blocks.append(ContentBlock(
                        block_type=BlockType.LIST,
                        text=text,
                    ))

            # ── 表格 ──
            elif name == "table":
                table_block = self._html_table_to_block(child)
                if table_block:
                    blocks.append(table_block)

            # ── Confluence 结构化宏 ──
            elif name == "ac:structured-macro":
                macro_block = self._handle_macro(child)
                if macro_block:
                    blocks.append(macro_block)

            # ── 容器标签：递归进入 ──
            elif name in ("ul", "ol", "div", "section", "article",
                          "main", "aside", "header", "footer", "blockquote",
                          "td", "th", "tr", "tbody", "thead"):
                self._walk_node(child, blocks)

            # ── 其他标签：忽略（如 <br>, <hr>, <span> 等）

    @staticmethod
    def _handle_macro(macro_tag: Tag) -> ContentBlock | None:
        """处理 Confluence <ac:structured-macro>，提取带标记的文本

        例如:
        - <ac:structured-macro ac:name="code"> → [CodeBlock: ...]
        - <ac:structured-macro ac:name="info">  → [Info: ...]
        - <ac:structured-macro ac:name="status"> → [Status: 已完成]
        """
        macro_name = macro_tag.get("ac:name", "")
        if not macro_name:
            return None

        prefix = _MACRO_PREFIXES.get(macro_name.lower(), f"[Macro:{macro_name}]")

        # 提取宏内部的文本内容
        # Confluence 宏结构: <ac:rich-text-body> 或直接子元素
        rich_body = macro_tag.find("ac:rich-text-body")
        if rich_body:
            inner_text = rich_body.get_text(strip=True)
        else:
            # fallback: 取所有直接文本
            inner_text = macro_tag.get_text(strip=True)

        # 对于 status 宏，尝试提取更具体的参数
        if macro_name.lower() == "status":
            status_param = macro_tag.find("ac:parameter", attrs={"ac:name": "colour"})
            colour = status_param.get_text(strip=True) if status_param else ""
            if inner_text:
                display_text = f"{prefix}: {inner_text}"
            else:
                display_text = f"{prefix}: {colour}" if colour else f"[Status]"
        elif inner_text:
            display_text = f"{prefix}: {inner_text}"
        else:
            display_text = f"{prefix}]"

        if not display_text.strip():
            return None

        return ContentBlock(
            block_type=BlockType.PARAGRAPH,
            text=display_text,
        )

    @staticmethod
    def _html_table_to_block(table_el: Tag) -> ContentBlock | None:
        """将 HTML <table> 转为 ContentBlock"""
        rows_el = table_el.find_all("tr")
        if not rows_el:
            return None

        all_rows: list[list[str]] = []
        for r in rows_el:
            cells = r.find_all(["td", "th"])
            row_data = [c.get_text(strip=True).replace("\n", " ") for c in cells]
            if any(row_data):
                all_rows.append(row_data)

        if not all_rows:
            return None

        headers = all_rows[0]
        body = all_rows[1:] if len(all_rows) > 1 else []
        return ContentBlock(
            block_type=BlockType.TABLE,
            headers=list(headers),
            rows=body,
        )

    # ════════════════════ 第三步：附件下载与解析 ════════════════════

    def _process_attachments(
        self, page_id: str, creds: dict
    ) -> tuple[list[Document], list[dict]]:
        """通过 Confluence API 下载并解析页面附件，每个成功解析的附件生成独立 Document

        Returns:
            (attachment_docs, attachments_processed_list)
            - attachment_docs: 每个成功解析的附件一个 Document
              （title=文件名, content_type="attachment", metadata 含 parent_page_id/attachment_id）
            - attachments_processed_list: 处理详情（含 success / reason / doc_id）
        """
        if not page_id:
            return [], []

        base = creds["base"]
        session = requests.Session()
        session.auth = (creds["email"], creds["token"])
        session.headers.update({"Accept": "application/json"})

        attachment_docs: list[Document] = []
        processed: list[dict] = []

        try:
            # 1. 列出附件
            att_list = self._api_get(
                session, base,
                f"/rest/api/content/{page_id}/child/attachment",
                params={"expand": "version"},
            )
            results = att_list.get("results", [])
            if not results:
                logger.info(f"页面 {page_id} 无附件")
                return [], []

            logger.info(f"页面 {page_id} 有 {len(results)} 个附件")

            # 2. 创建临时目录
            tmp_dir = tempfile.mkdtemp(prefix="confluence_att_")

            try:
                for att in results:
                    att_id = att["id"]
                    filename = att.get("title", "unknown")
                    # 使用 API 返回的附件直链下载（不能自己拼 /data 端点，否则 405）
                    download_url = att.get("_links", {}).get("download", "")
                    if download_url and not download_url.startswith("http"):
                        download_url = base + download_url
                    ext = os.path.splitext(filename)[1].lower()

                    entry: dict = {
                        "attachment_id": att_id,
                        "filename": filename,
                        "success": False,
                        "reason": "",
                    }

                    try:
                        # 3. 下载附件
                        if not download_url:
                            entry["reason"] = "no_download_link"
                            processed.append(entry)
                            continue
                        local_path = os.path.join(tmp_dir, filename)
                        download_ok = self._download_attachment(
                            session, download_url, local_path,
                        )
                        if not download_ok:
                            entry["reason"] = "download_failed"
                            processed.append(entry)
                            continue

                        # 4. 根据类型分发解析 → 生成独立 Document
                        if ext in _ATTACHMENT_PARSERS:
                            att_doc = self._parse_attachment_file(local_path, ext)
                            if att_doc and att_doc.content_blocks:
                                att_doc_id = self._generate_doc_id(
                                    download_url, f"{page_id}:{att_id}"
                                )
                                att_meta = {
                                    "source_url": download_url,
                                    "space_key": creds.get("space_key", ""),
                                    "parent_page_id": page_id,
                                    "attachment_id": att_id,
                                    "content_type": "attachment",
                                    "source_type": "confluence_attachment",
                                    "filename": filename,
                                    "last_updated": att.get("version", {}).get("when", ""),
                                }
                                meta = dict(att_doc.metadata or {})
                                meta.update(att_meta)
                                att_doc.doc_id = att_doc_id
                                att_doc.title = filename
                                att_doc.space = creds.get("space_key", "confluence")
                                att_doc.address = download_url
                                att_doc.source_url = download_url
                                att_doc.last_updated = att_meta["last_updated"]
                                att_doc.metadata = meta
                                attachment_docs.append(att_doc)
                                entry["success"] = True
                                entry["reason"] = "parsed"
                                entry["doc_id"] = att_doc_id
                            else:
                                entry["reason"] = "parse_error"
                        else:
                            # 不支持的类型（图片等），记录日志后跳过
                            logger.info(f"跳过不支持的附件类型: {filename} ({ext})")
                            entry["reason"] = "unsupported_type"

                    except Exception as e:
                        logger.error(f"附件处理异常 [{filename}]: {e}")
                        entry["reason"] = f"error: {e}"

                    processed.append(entry)

            finally:
                # 5. 清理临时目录
                shutil.rmtree(tmp_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"附件列表获取失败 [page_id={page_id}]: {e}")
            processed.append({
                "attachment_id": "", "filename": "",
                "success": False, "reason": f"list_failed: {e}",
            })

        return attachment_docs, processed

    def _load_local_attachments(
        self, source: str
    ) -> tuple[list[Document], list[dict]]:
        """从本地 _attachments/ 目录加载已下载的附件，每个附件生成独立 Document（Batch 模式回退）"""
        attachment_docs: list[Document] = []
        processed: list[dict] = []

        # source 可能是文件路径或 URL
        if os.path.isfile(source):
            base_dir = os.path.dirname(source)
        else:
            return [], []

        att_dir = os.path.join(base_dir, "_attachments")
        if not os.path.isdir(att_dir):
            return [], []

        page_id = os.path.splitext(os.path.basename(source))[0]

        for fname in sorted(os.listdir(att_dir)):
            fpath = os.path.join(att_dir, fname)
            if not os.path.isfile(fpath):
                continue
            ext = os.path.splitext(fname)[1].lower()
            entry: dict = {
                "attachment_id": "",
                "filename": fname,
                "success": False,
                "reason": "",
            }
            try:
                if ext in _ATTACHMENT_PARSERS:
                    att_doc = self._parse_attachment_file(fpath, ext)
                    if att_doc and att_doc.content_blocks:
                        att_doc_id = self._generate_doc_id(fpath, f"local:{fname}")
                        att_meta = {
                            "source_url": fpath,
                            "space_key": "local",
                            "parent_page_id": f"local:{page_id}",
                            "content_type": "attachment",
                            "source_type": "local_attachment",
                            "filename": fname,
                        }
                        meta = dict(att_doc.metadata or {})
                        meta.update(att_meta)
                        att_doc.doc_id = att_doc_id
                        att_doc.title = fname
                        att_doc.space = "local"
                        att_doc.address = fpath
                        att_doc.source_url = fpath
                        att_doc.metadata = meta
                        attachment_docs.append(att_doc)
                        entry["success"] = True
                        entry["reason"] = "parsed"
                        entry["doc_id"] = att_doc_id
                    else:
                        entry["reason"] = "parse_error"
                else:
                    entry["reason"] = "unsupported_type"
            except Exception as e:
                entry["reason"] = f"error: {e}"
            processed.append(entry)

        return attachment_docs, processed

    # ─────────────────────── 附件辅助方法 ───────────────────────

    @staticmethod
    def _api_get(session: requests.Session, base: str, path: str, params=None, tries: int = 3):
        """Confluence API GET 请求（带限流重试）"""
        import time
        url = base + path
        for attempt in range(tries):
            r = session.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"API 限流(429)，{wait}s 后重试...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("Confluence API 多次限流，已放弃")

    @staticmethod
    def _download_attachment(
        session: requests.Session, download_url: str, local_path: str,
    ) -> bool:
        """下载单个附件到本地路径（使用 attachment 的 _links.download 直链）

        注意：附件下载是二进制流，不能带 application/json 的 Accept 头，
        否则 Confluence 会返回 405/406。这里强制用 */* 并覆盖 JSON 头。

        对瞬时网络错误（连接中断、IncompleteRead、DNS 抖动）做指数退避重试，
        避免大文件下载偶发失败导致整页附件丢失。
        """
        import time
        headers = {"Accept": "*/*"}
        max_retries = 4
        for attempt in range(max_retries):
            try:
                # stream=True：边下边写，遇到截断可重试而不占内存
                with session.get(
                    download_url, headers=headers, timeout=120, stream=True
                ) as r:
                    if r.status_code != 200:
                        logger.error(
                            f"附件下载失败 [{download_url[:100]}]: HTTP {r.status_code}"
                        )
                        return False
                    with open(local_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                # 校验文件非空
                if os.path.getsize(local_path) == 0:
                    raise IOError("下载文件为空")
                return True
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.Timeout,
                    IOError) as e:
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"附件下载中断（{type(e).__name__}），{wait}s 后重试 "
                        f"({attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait)
                    # 删除可能不完整的残文件
                    try:
                        os.remove(local_path)
                    except OSError:
                        pass
                    continue
                logger.error(f"附件下载最终失败 [{download_url[:100]}]: {e}")
                return False
        return False

    @staticmethod
    def _parse_attachment_file(file_path: str, ext: str) -> Document | None:
        """根据扩展名选择对应解析器解析附件文件"""
        parser_class_path = _ATTACHMENT_PARSERS.get(ext)
        if not parser_class_path:
            return None

        try:
            # 动态导入解析器类
            module_path, class_name = parser_class_path.rsplit(".", 1)
            import importlib
            module = importlib.import_module(module_path)
            parser_cls = getattr(module, class_name)
            parser = parser_cls()
            return parser.parse(file_path)
        except Exception as e:
            logger.error(f"附件解析失败 [{file_path}]: {e}")
            return None

    # ─────────────────────── 工具方法 ───────────────────────

    @staticmethod
    def supported_extensions() -> list[str]:
        return [".html", ".htm"]

    @staticmethod
    def _generate_doc_id(source: str, page_id: str = "") -> str:
        """生成幂等 doc_id：优先用 page_id，否则对 source 做 hash"""
        import hashlib
        raw = page_id if page_id else source
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _load_sidecar(file_path: str) -> dict:
        """加载同目录下的侧车元数据文件 <file>.meta.json"""
        import json
        meta_path = file_path + ".meta.json"
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @staticmethod
    def _clean_text(text: str) -> str:
        """清理多余空白"""
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()
