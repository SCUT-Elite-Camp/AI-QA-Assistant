"""Deterministic layout extraction helpers for native PDF text blocks."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import pymupdf as fitz

from models.document import BlockType, BoundingBox, ContentBlock


EDGE_RATIO = 0.12
SPANNING_WIDTH_RATIO = 0.70
MIN_COLUMN_GAP_RATIO = 0.08
MIN_COLUMN_GUTTER_RATIO = 0.02
_PAGE_NUMBER_KEY = "<page-number>"
_PAGE_NUMBER_ONLY = re.compile(r"^(?:page\s*)?[-–—]?\s*\d+\s*[-–—]?$", re.IGNORECASE)


@dataclass(frozen=True)
class LayoutBlock:
    """A page text block before public ``ContentBlock`` conversion."""

    text: str
    bbox: tuple[float, float, float, float]
    font_size: float
    font_name: str
    flags: int
    rotation: float
    page_number: int
    ordinal: int
    page_width: float
    page_height: float
    direction: tuple[float, float] = (1.0, 0.0)
    confidence: float = 1.0
    extraction_method: str = "pymupdf"

    @property
    def bold(self) -> bool:
        return bool(self.flags & fitz.TEXT_FONT_BOLD)

    @property
    def italic(self) -> bool:
        return bool(self.flags & fitz.TEXT_FONT_ITALIC)

    def to_content_block(self) -> ContentBlock:
        """Convert the internal block without dropping source provenance."""
        x0, y0, x1, y1 = self.bbox
        return ContentBlock(
            block_type=BlockType.PARAGRAPH,
            text=self.text,
            block_id=f"page-{self.page_number}-block-{self.ordinal}",
            page_number=self.page_number,
            bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1),
            font_name=self.font_name,
            font_size=self.font_size,
            rotation=self.rotation,
            confidence=self.confidence,
            source="native",
            extraction_method=self.extraction_method,
            bold=self.bold,
            italic=self.italic,
        )


@dataclass
class LayoutDiagnostics:
    removed_headers: int = 0
    removed_footers: int = 0
    partial_table_overlaps: int = 0


def extract_layout_blocks(page, page_number: int) -> list[LayoutBlock]:
    """Extract text blocks with font, geometry, direction, and source metadata."""
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    text_dict = page.get_text("dict", sort=False)
    result: list[LayoutBlock] = []

    for raw_block in text_dict.get("blocks", []):
        if raw_block.get("type") != 0:
            continue
        for lines, bbox in _partition_raw_block(raw_block, page_width):
            block = _layout_block_from_lines(
                lines,
                bbox=bbox,
                page_number=page_number,
                ordinal=len(result),
                page_width=page_width,
                page_height=page_height,
            )
            if block is not None:
                result.append(block)

    return result


def _layout_block_from_lines(
    lines: Sequence[dict],
    *,
    bbox: tuple[float, float, float, float],
    page_number: int,
    ordinal: int,
    page_width: float,
    page_height: float,
) -> LayoutBlock | None:
    line_texts: list[str] = []
    font_weights: dict[str, int] = defaultdict(int)
    font_order: list[str] = []
    direction_weights: dict[tuple[float, float], int] = defaultdict(int)
    max_font_size = 0.0
    flags = 0

    for line in lines:
        spans = line.get("spans", [])
        line_text = "".join(str(span.get("text", "")) for span in spans).strip()
        if line_text:
            line_texts.append(line_text)
        direction = _coerce_direction(line.get("dir", (1.0, 0.0)))
        direction_weights[direction] += max(1, len(line_text))
        for span in spans:
            span_text = str(span.get("text", ""))
            font_name = str(span.get("font", ""))
            if font_name and font_name not in font_weights:
                font_order.append(font_name)
            if font_name:
                font_weights[font_name] += max(1, len(span_text.strip()))
            max_font_size = max(max_font_size, float(span.get("size", 0.0) or 0.0))
            flags |= int(span.get("flags", 0) or 0)

    text = "\n".join(line_texts).strip()
    if not text:
        return None
    dominant_font = max(font_order, key=lambda name: font_weights[name]) if font_order else ""
    direction = max(direction_weights, key=direction_weights.get) if direction_weights else (1.0, 0.0)
    rotation = math.degrees(math.atan2(direction[1], direction[0]))
    return LayoutBlock(
        text=text,
        bbox=bbox,
        font_size=max_font_size,
        font_name=dominant_font,
        flags=flags,
        rotation=rotation,
        direction=direction,
        page_number=page_number,
        ordinal=ordinal,
        page_width=page_width,
        page_height=page_height,
    )


def _partition_raw_block(
    raw_block: dict,
    page_width: float,
) -> list[tuple[list[dict], tuple[float, float, float, float]]]:
    """Split a PyMuPDF block only when it contains side-by-side line groups."""
    raw_bbox = _coerce_bbox(raw_block.get("bbox"))
    if raw_bbox is None:
        return []
    lines = list(raw_block.get("lines", []))
    positioned = [
        (line, line_bbox)
        for line in lines
        for line_bbox in (_coerce_bbox(line.get("bbox")),)
        if line_bbox is not None
    ]
    if len(positioned) < 2:
        return [(lines, raw_bbox)]

    positioned.sort(key=lambda item: ((item[1][0] + item[1][2]) / 2.0, item[1][1]))
    gaps = [
        (((right[1][0] + right[1][2]) - (left[1][0] + left[1][2])) / 2.0, index)
        for index, (left, right) in enumerate(zip(positioned, positioned[1:]), start=1)
    ]
    largest_gap, split_at = max(gaps, key=lambda item: item[0])
    left = positioned[:split_at]
    right = positioned[split_at:]
    if largest_gap < page_width * MIN_COLUMN_GAP_RATIO or not _groups_share_vertical_band(left, right):
        return [(lines, raw_bbox)]
    return [
        ([line for line, _ in group], _union_bboxes(bbox for _, bbox in group))
        for group in (left, right)
    ]


def normalize_edge_text(text: str) -> str:
    """Normalize edge text for cross-page comparison."""
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    if normalized and _PAGE_NUMBER_ONLY.fullmatch(normalized):
        return _PAGE_NUMBER_KEY
    return normalized


def find_repeated_edge_keys(pages: Sequence[Sequence[LayoutBlock]]) -> set[str]:
    """Find edge strings repeated on enough distinct, similarly positioned pages."""
    return set(_find_repeated_edge_clusters(pages))


def _find_repeated_edge_clusters(
    pages: Sequence[Sequence[LayoutBlock]],
) -> dict[str, list[_EdgeCluster]]:
    page_count = len(pages)
    if page_count < 2:
        return {}
    required_pages = max(2, math.ceil(page_count * 0.5))
    clusters: dict[str, list[_EdgeCluster]] = defaultdict(list)

    for page in pages:
        for block in page:
            edge = _edge_kind(block)
            key = normalize_edge_text(block.text)
            if edge is None or not key:
                continue
            y_position = _relative_y(block)
            x_position = _relative_x(block)
            cluster = next(
                (
                    candidate
                    for candidate in clusters[key]
                    if candidate.edge == edge
                    and abs(candidate.y_position - y_position) <= 0.03
                    and abs(candidate.x_position - x_position) <= 0.12
                ),
                None,
            )
            if cluster is None:
                cluster = _EdgeCluster(edge=edge, y_position=y_position, x_position=x_position)
                clusters[key].append(cluster)
            cluster.pages.add(block.page_number)

    repeated: dict[str, list[_EdgeCluster]] = defaultdict(list)
    for key, key_clusters in clusters.items():
        for cluster in key_clusters:
            if len(cluster.pages) < required_pages:
                continue
            if key == _PAGE_NUMBER_KEY and not _has_consecutive_pages(cluster.pages):
                continue
            repeated[key].append(cluster)
    return dict(repeated)


def filter_repeated_edge_blocks(
    pages: Sequence[Sequence[LayoutBlock]],
    repeated_keys: set[str] | None = None,
) -> tuple[list[list[LayoutBlock]], LayoutDiagnostics]:
    """Remove only repeated edge blocks and report header/footer counts."""
    repeated_clusters = _find_repeated_edge_clusters(pages)
    keys = repeated_keys if repeated_keys is not None else set(repeated_clusters)
    diagnostics = LayoutDiagnostics()
    filtered_pages: list[list[LayoutBlock]] = []
    for page in pages:
        filtered: list[LayoutBlock] = []
        for block in page:
            edge = _edge_kind(block)
            key = normalize_edge_text(block.text)
            matching_cluster = next(
                (
                    cluster
                    for cluster in repeated_clusters.get(key, [])
                    if cluster.edge == edge
                    and abs(cluster.y_position - _relative_y(block)) <= 0.03
                    and abs(cluster.x_position - _relative_x(block)) <= 0.12
                ),
                None,
            )
            if key in keys and matching_cluster is not None:
                if edge == "header":
                    diagnostics.removed_headers += 1
                else:
                    diagnostics.removed_footers += 1
                continue
            filtered.append(block)
        filtered_pages.append(filtered)
    return filtered_pages, diagnostics


def order_layout_blocks(blocks: Sequence[LayoutBlock], page_width: float) -> list[LayoutBlock]:
    """Order common single- and two-column layouts deterministically."""
    if not blocks:
        return []
    spanning = [block for block in blocks if _block_width(block) >= page_width * SPANNING_WIDTH_RATIO]
    if not spanning:
        return _order_column_section(blocks, page_width)

    ordered: list[LayoutBlock] = []
    remaining = list(blocks)
    for spanning_block in _fallback_sort(spanning):
        span_midpoint = _vertical_midpoint(spanning_block)
        above = [
            block
            for block in remaining
            if block is not spanning_block and _vertical_midpoint(block) < span_midpoint
        ]
        ordered.extend(_order_column_section(above, page_width))
        ordered.append(spanning_block)
        consumed_ids = {id(block) for block in above}
        consumed_ids.add(id(spanning_block))
        remaining = [block for block in remaining if id(block) not in consumed_ids]
    ordered.extend(_order_column_section(remaining, page_width))
    return ordered


@dataclass
class _EdgeCluster:
    edge: str
    y_position: float
    x_position: float
    pages: set[int] = field(default_factory=set)


def _order_column_section(blocks: Iterable[LayoutBlock], page_width: float) -> list[LayoutBlock]:
    section = list(blocks)
    if len(section) < 4:
        return _fallback_sort(section)
    by_center = sorted(section, key=lambda block: (_horizontal_midpoint(block), block.ordinal))
    gaps = [
        (_horizontal_midpoint(right) - _horizontal_midpoint(left), index)
        for index, (left, right) in enumerate(zip(by_center, by_center[1:]), start=1)
    ]
    if not gaps:
        return _fallback_sort(section)
    largest_gap, split_at = max(gaps, key=lambda item: item[0])
    left_column = by_center[:split_at]
    right_column = by_center[split_at:]
    if (
        largest_gap < page_width * MIN_COLUMN_GAP_RATIO
        or len(left_column) < 2
        or len(right_column) < 2
        or not _columns_are_spatially_parallel(left_column, right_column, page_width)
    ):
        return _fallback_sort(section)
    return _fallback_sort(left_column) + _fallback_sort(right_column)


def _fallback_sort(blocks: Iterable[LayoutBlock]) -> list[LayoutBlock]:
    return sorted(blocks, key=lambda block: (block.bbox[1], block.bbox[0], block.ordinal))


def _columns_are_spatially_parallel(
    left_column: Sequence[LayoutBlock],
    right_column: Sequence[LayoutBlock],
    page_width: float,
) -> bool:
    gutter = min(block.bbox[0] for block in right_column) - max(
        block.bbox[2] for block in left_column
    )
    if gutter < page_width * MIN_COLUMN_GUTTER_RATIO:
        return False

    left_y0 = min(block.bbox[1] for block in left_column)
    left_y1 = max(block.bbox[3] for block in left_column)
    right_y0 = min(block.bbox[1] for block in right_column)
    right_y1 = max(block.bbox[3] for block in right_column)
    return min(left_y1, right_y1) > max(left_y0, right_y0)


def _edge_kind(block: LayoutBlock) -> str | None:
    midpoint = _vertical_midpoint(block)
    if midpoint <= block.page_height * EDGE_RATIO:
        return "header"
    if midpoint >= block.page_height * (1.0 - EDGE_RATIO):
        return "footer"
    return None


def _relative_y(block: LayoutBlock) -> float:
    return _vertical_midpoint(block) / max(1.0, block.page_height)


def _relative_x(block: LayoutBlock) -> float:
    return _horizontal_midpoint(block) / max(1.0, block.page_width)


def _horizontal_midpoint(block: LayoutBlock) -> float:
    return (block.bbox[0] + block.bbox[2]) / 2.0


def _vertical_midpoint(block: LayoutBlock) -> float:
    return (block.bbox[1] + block.bbox[3]) / 2.0


def _block_width(block: LayoutBlock) -> float:
    return max(0.0, block.bbox[2] - block.bbox[0])


def _coerce_bbox(value) -> tuple[float, float, float, float] | None:
    try:
        x0, y0, x1, y1 = (float(coordinate) for coordinate in value)
    except (TypeError, ValueError):
        return None
    if x1 < x0 or y1 < y0:
        return None
    return x0, y0, x1, y1


def _coerce_direction(value) -> tuple[float, float]:
    try:
        dx, dy = value
        return float(dx), float(dy)
    except (TypeError, ValueError):
        return 1.0, 0.0


def _groups_share_vertical_band(
    left: Sequence[tuple[dict, tuple[float, float, float, float]]],
    right: Sequence[tuple[dict, tuple[float, float, float, float]]],
) -> bool:
    left_y0 = min(bbox[1] for _, bbox in left)
    left_y1 = max(bbox[3] for _, bbox in left)
    right_y0 = min(bbox[1] for _, bbox in right)
    right_y1 = max(bbox[3] for _, bbox in right)
    return min(left_y1, right_y1) >= max(left_y0, right_y0)


def _union_bboxes(
    bboxes: Iterable[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    values = list(bboxes)
    return (
        min(bbox[0] for bbox in values),
        min(bbox[1] for bbox in values),
        max(bbox[2] for bbox in values),
        max(bbox[3] for bbox in values),
    )


def _has_consecutive_pages(pages: set[int]) -> bool:
    ordered = sorted(pages)
    return any(right == left + 1 for left, right in zip(ordered, ordered[1:]))
