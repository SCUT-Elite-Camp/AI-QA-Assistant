"""Concrete table backends with lazy optional dependencies."""

from __future__ import annotations

import importlib.util
import re
import time
from html.parser import HTMLParser
from typing import Any, Iterable

from models.document import BoundingBox, TableArtifact, TableCell


class PyMuPDFTableBackend:
    name = "pymupdf"

    def available(self) -> bool:
        return True

    def extract(self, page: Any, page_number: int, file_path: str | None = None) -> list[TableArtifact]:
        started = time.perf_counter()
        finder = page.find_tables()
        tables = getattr(finder, "tables", finder)
        artifacts: list[TableArtifact] = []
        for index, table in enumerate(tables, start=1):
            try:
                rows = table.extract()
                x0, y0, x1, y1 = map(float, table.bbox)
                bbox = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
            except Exception:
                continue
            artifact = artifact_from_rows(
                rows,
                table_id=f"page-{page_number}-pymupdf-{index}",
                parser_name=self.name,
                page_number=page_number,
                bbox=bbox,
                confidence=_heuristic_backend_confidence(rows),
            )
            if artifact is not None:
                artifact.elapsed_ms = (time.perf_counter() - started) * 1000
                artifacts.append(artifact)
        return artifacts


class CamelotTableBackend:
    name = "camelot"

    def available(self) -> bool:
        return importlib.util.find_spec("camelot") is not None

    def extract(self, page: Any, page_number: int, file_path: str | None = None) -> list[TableArtifact]:
        if not file_path:
            return []
        import camelot

        started = time.perf_counter()
        artifacts: list[TableArtifact] = []
        for flavor in ("lattice", "stream"):
            try:
                tables = camelot.read_pdf(file_path, pages=str(page_number), flavor=flavor)
            except Exception:
                continue
            for index, table in enumerate(tables, start=1):
                rows = table.df.fillna("").astype(str).values.tolist()
                bbox = _camelot_bbox(table, page)
                report = getattr(table, "parsing_report", {}) or {}
                accuracy = float(report.get("accuracy", 70.0)) / 100.0
                whitespace = float(report.get("whitespace", 0.0)) / 100.0
                confidence = max(0.0, min(1.0, accuracy * (1.0 - 0.35 * whitespace)))
                artifact = artifact_from_rows(
                    rows,
                    table_id=f"page-{page_number}-camelot-{flavor}-{index}",
                    parser_name=f"camelot:{flavor}",
                    page_number=page_number,
                    bbox=bbox,
                    confidence=confidence,
                )
                if artifact is not None:
                    artifact.elapsed_ms = (time.perf_counter() - started) * 1000
                    artifacts.append(artifact)
        return _deduplicate_exact_tables(artifacts)


class GMFTTableBackend:
    """Learned fallback for complex born-digital PDF tables."""

    name = "gmft"

    def __init__(self) -> None:
        self._detector: Any | None = None
        self._formatter: Any | None = None

    def available(self) -> bool:
        return importlib.util.find_spec("gmft") is not None

    def should_run(self, page: Any) -> bool:
        """Avoid loading TATR on prose-only pages with no grid-like alignment."""
        try:
            words = page.get_text("words")
        except Exception:
            return True
        if len(words) < 6:
            return False

        lines: dict[tuple[int, int], set[int]] = {}
        for word in words:
            if len(word) < 5 or not str(word[4]).strip():
                continue
            if len(word) >= 7:
                line_key = (int(word[5]), int(word[6]))
            else:
                line_key = (0, round(float(word[1]) / 4))
            # Eight PDF points tolerates minor font/layout jitter while keeping
            # genuinely different columns separate.
            lines.setdefault(line_key, set()).add(round(float(word[0]) / 8))

        column_lines: dict[int, set[tuple[int, int]]] = {}
        for line_key, columns in lines.items():
            for column in columns:
                column_lines.setdefault(column, set()).add(line_key)
        stable_columns = sum(len(line_keys) >= 3 for line_keys in column_lines.values())
        return len(lines) >= 3 and stable_columns >= 2

    def extract(self, page: Any, page_number: int, file_path: str | None = None) -> list[TableArtifact]:
        if not file_path:
            return []

        from gmft.auto import AutoTableDetector, AutoTableFormatter
        from gmft.pdf_bindings import PyPDFium2Document

        if self._detector is None:
            self._detector = AutoTableDetector()
        if self._formatter is None:
            self._formatter = AutoTableFormatter()

        started = time.perf_counter()
        document = PyPDFium2Document(file_path)
        try:
            gmft_page = document[page_number - 1]
            detected = self._detector.extract(gmft_page)
            artifacts: list[TableArtifact] = []
            for index, table in enumerate(detected, start=1):
                try:
                    formatted = self._formatter.extract(table)
                    frame = formatted.df()
                    rows = _gmft_rows(frame)
                    raw_bbox = tuple(float(value) for value in table.bbox)
                    bbox = BoundingBox(
                        x0=raw_bbox[0],
                        y0=raw_bbox[1],
                        x1=raw_bbox[2],
                        y1=raw_bbox[3],
                    )
                    confidence = float(getattr(table, "confidence_score", 0.7))
                except Exception:
                    continue
                artifact = artifact_from_rows(
                    rows,
                    table_id=f"page-{page_number}-gmft-{index}",
                    parser_name="gmft:tatr",
                    page_number=page_number,
                    bbox=bbox,
                    confidence=confidence,
                )
                if artifact is not None:
                    artifact.elapsed_ms = (time.perf_counter() - started) * 1000
                    artifacts.append(artifact)
            return artifacts
        finally:
            document.close()


class PaddleOCRTableBackend:
    name = "paddle"

    def available(self) -> bool:
        return importlib.util.find_spec("paddleocr") is not None

    def extract(self, page: Any, page_number: int, file_path: str | None = None) -> list[TableArtifact]:
        import numpy as np
        import pymupdf
        from paddleocr import PPStructureV3

        started = time.perf_counter()
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
            pixmap.height,
            pixmap.width,
            pixmap.n,
        )
        pipeline = PPStructureV3()
        try:
            results = pipeline.predict(input=image)
        except TypeError:
            results = pipeline.predict(image)

        artifacts: list[TableArtifact] = []
        for index, payload in enumerate(_table_payloads(results), start=1):
            html = payload.get("pred_html") or payload.get("html") or payload.get("table_html")
            if not html:
                continue
            parsed = _parse_html_table(str(html))
            if parsed is None:
                continue
            cells, row_count, column_count = parsed
            bbox = _payload_bbox(payload, page, pixmap)
            confidence = float(payload.get("confidence", payload.get("score", 0.7)))
            artifacts.append(TableArtifact(
                table_id=f"page-{page_number}-paddle-{index}",
                cells=cells,
                row_count=row_count,
                column_count=column_count,
                header_row_count=_header_count_from_cells(cells),
                page_number=page_number,
                bbox=bbox,
                parser_name=self.name,
                confidence=max(0.0, min(1.0, confidence)),
                elapsed_ms=(time.perf_counter() - started) * 1000,
            ))
        return artifacts


def artifact_from_rows(
    rows: Iterable[Iterable[Any]],
    *,
    table_id: str,
    parser_name: str,
    page_number: int,
    bbox: BoundingBox | None,
    confidence: float,
) -> TableArtifact | None:
    normalized = [[str(value or "").strip() for value in row] for row in rows]
    normalized = [row for row in normalized if any(row)]
    if not normalized:
        return None
    column_count = max(len(row) for row in normalized)
    normalized = [row + [""] * (column_count - len(row)) for row in normalized]
    header_row_count = _infer_header_row_count(normalized)
    cells = [
        TableCell(
            row_index=row_index,
            column_index=column_index,
            text=value,
            is_header=row_index < header_row_count,
        )
        for row_index, row in enumerate(normalized)
        for column_index, value in enumerate(row)
    ]
    return TableArtifact(
        table_id=table_id,
        cells=cells,
        row_count=len(normalized),
        column_count=column_count,
        header_row_count=header_row_count,
        page_number=page_number,
        bbox=bbox,
        parser_name=parser_name,
        confidence=max(0.0, min(1.0, confidence)),
    )


def _gmft_rows(frame: Any) -> list[list[str]]:
    normalized = frame.fillna("").astype(str)
    rows = normalized.values.tolist()
    raw_columns = list(getattr(normalized, "columns", []))
    if not raw_columns:
        return rows
    columns = [_column_label(value) for value in raw_columns]
    default_columns = all(
        value == str(index)
        for index, value in enumerate(columns)
    )
    if not default_columns and any(columns) and (not rows or columns != rows[0]):
        rows.insert(0, columns)
    return rows


def _column_label(value: Any) -> str:
    if isinstance(value, tuple):
        parts = [str(part).strip() for part in value if str(part).strip()]
        return " / ".join(dict.fromkeys(parts))
    return str(value).strip()


def _infer_header_row_count(rows: list[list[str]]) -> int:
    if len(rows) < 2:
        return 0
    first = rows[0]
    second = rows[1]
    if not any(first):
        return 0
    first_numeric = sum(_looks_numeric(value) for value in first if value)
    second_numeric = sum(_looks_numeric(value) for value in second if value)
    first_nonempty = sum(bool(value) for value in first)
    return 1 if first_numeric == 0 and second_numeric > 0 and first_nonempty >= max(1, len(first) // 2) else 0


def _looks_numeric(value: str) -> bool:
    compact = value.strip().replace(",", "").replace("%", "")
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", compact))


def _heuristic_backend_confidence(rows: Iterable[Iterable[Any]]) -> float:
    normalized = [[str(value or "").strip() for value in row] for row in rows]
    slots = sum(len(row) for row in normalized)
    nonempty = sum(bool(value) for row in normalized for value in row)
    return 0.55 + 0.35 * (nonempty / max(1, slots))


def _camelot_bbox(table: Any, page: Any) -> BoundingBox | None:
    raw = getattr(table, "_bbox", None)
    if not raw or len(raw) != 4:
        return None
    x0, y0, x1, y1 = map(float, raw)
    height = float(page.rect.height)
    return BoundingBox(x0=x0, y0=height - y1, x1=x1, y1=height - y0)


def _deduplicate_exact_tables(artifacts: list[TableArtifact]) -> list[TableArtifact]:
    unique: dict[tuple, TableArtifact] = {}
    for artifact in artifacts:
        key = (
            tuple(tuple(row) for row in artifact.to_matrix()),
            tuple(artifact.bbox.model_dump().values()) if artifact.bbox else None,
        )
        existing = unique.get(key)
        if existing is None or artifact.confidence > existing.confidence:
            unique[key] = artifact
    return list(unique.values())


def _table_payloads(results: Any) -> Iterable[dict[str, Any]]:
    if results is None:
        return []
    found: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if hasattr(value, "json"):
            json_value = value.json
            value = json_value() if callable(json_value) else json_value
        if isinstance(value, dict):
            if any(key in value for key in ("pred_html", "table_html", "html")):
                found.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)
        elif not isinstance(value, (str, bytes)):
            try:
                for child in value:
                    visit(child)
            except TypeError:
                return

    visit(results)
    return found


def _payload_bbox(payload: dict[str, Any], page: Any, pixmap: Any) -> BoundingBox | None:
    raw = payload.get("bbox") or payload.get("box") or payload.get("coordinate")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    scale_x = float(page.rect.width) / max(1.0, float(pixmap.width))
    scale_y = float(page.rect.height) / max(1.0, float(pixmap.height))
    x0, y0, x1, y1 = map(float, raw)
    return BoundingBox(x0=x0 * scale_x, y0=y0 * scale_y, x1=x1 * scale_x, y1=y1 * scale_y)


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[tuple[str, int, int, bool]]] = []
        self.current_row: list[tuple[str, int, int, bool]] | None = None
        self.current_cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.current_row = []
        elif tag in ("td", "th") and self.current_row is not None:
            values = dict(attrs)
            self.current_cell = {
                "parts": [],
                "rowspan": int(values.get("rowspan") or 1),
                "colspan": int(values.get("colspan") or 1),
                "header": tag == "th",
            }
        elif tag == "br" and self.current_cell is not None:
            self.current_cell["parts"].append("\n")

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.current_cell is not None and self.current_row is not None:
            self.current_row.append((
                "".join(self.current_cell["parts"]).strip(),
                self.current_cell["rowspan"],
                self.current_cell["colspan"],
                self.current_cell["header"],
            ))
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            self.rows.append(self.current_row)
            self.current_row = None


def _parse_html_table(html: str) -> tuple[list[TableCell], int, int] | None:
    parser = _TableHTMLParser()
    parser.feed(html)
    if not parser.rows:
        return None
    occupied: set[tuple[int, int]] = set()
    cells: list[TableCell] = []
    column_count = 0
    for row_index, row in enumerate(parser.rows):
        column_index = 0
        for text, row_span, column_span, is_header in row:
            while (row_index, column_index) in occupied:
                column_index += 1
            cells.append(TableCell(
                row_index=row_index,
                column_index=column_index,
                text=text,
                row_span=row_span,
                column_span=column_span,
                is_header=is_header,
            ))
            for covered_row in range(row_index, row_index + row_span):
                for covered_column in range(column_index, column_index + column_span):
                    occupied.add((covered_row, covered_column))
            column_index += column_span
            column_count = max(column_count, column_index)
    row_count = max(row for row, _ in occupied) + 1
    return cells, row_count, column_count


def _header_count_from_cells(cells: list[TableCell]) -> int:
    header_rows = {cell.row_index for cell in cells if cell.is_header}
    count = 0
    while count in header_rows:
        count += 1
    return count
