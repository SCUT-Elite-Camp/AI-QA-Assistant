"""Optional, best-effort page OCR support for PDF parsing."""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from typing import Protocol

import pymupdf as fitz

from models.document import ContentBlock
from parsers.pdf_layout import extract_layout_blocks_from_dict


MIN_USABLE_CHARACTER_DENSITY = 0.00002
MAX_REPLACEMENT_CHARACTER_RATIO = 0.10
MAX_CONTROL_CHARACTER_RATIO = 0.05
DOMINANT_IMAGE_COVERAGE = 0.60
IMAGE_PAGE_SPARSE_CHARACTER_COUNT = 40
DEFAULT_OCR_CONFIDENCE = 0.75


class PageOCRBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def extract(self, page, page_number: int) -> list[ContentBlock]: ...


@dataclass(frozen=True)
class PageTextQuality:
    usable_character_count: int
    usable_character_density: float
    replacement_character_ratio: float
    control_character_ratio: float
    page_image_coverage: float
    needs_ocr: bool
    reasons: tuple[str, ...]


def evaluate_page_text_quality(page, native_blocks) -> PageTextQuality:
    """Score native page text and decide whether page-level OCR is warranted."""
    text = "\n".join(str(getattr(block, "text", "")) for block in native_blocks)
    characters = [character for character in text if not character.isspace()]
    replacement_count = sum(character == "\ufffd" for character in characters)
    control_count = sum(
        unicodedata.category(character).startswith("C") and character != "\ufffd"
        for character in characters
    )
    usable_count = sum(
        character != "\ufffd"
        and not unicodedata.category(character).startswith("C")
        and character.isprintable()
        for character in characters
    )
    character_count = len(characters)
    page_area = max(1.0, float(page.rect.width) * float(page.rect.height))
    density = usable_count / page_area
    replacement_ratio = replacement_count / max(1, character_count)
    control_ratio = control_count / max(1, character_count)
    image_coverage = _page_image_coverage(page, page_area)

    reasons: list[str] = []
    if usable_count == 0:
        reasons.append("empty_text")
    elif density < MIN_USABLE_CHARACTER_DENSITY:
        reasons.append("sparse_text")
    if replacement_ratio >= MAX_REPLACEMENT_CHARACTER_RATIO:
        reasons.append("replacement_characters")
    if control_ratio >= MAX_CONTROL_CHARACTER_RATIO:
        reasons.append("control_characters")
    if (
        image_coverage >= DOMINANT_IMAGE_COVERAGE
        and usable_count < IMAGE_PAGE_SPARSE_CHARACTER_COUNT
    ):
        reasons.append("image_dominated")

    return PageTextQuality(
        usable_character_count=usable_count,
        usable_character_density=density,
        replacement_character_ratio=replacement_ratio,
        control_character_ratio=control_ratio,
        page_image_coverage=image_coverage,
        needs_ocr=bool(reasons),
        reasons=tuple(reasons),
    )


class PyMuPDFOCRBackend:
    name = "pymupdf-ocr"

    def available(self) -> bool:
        try:
            return bool(fitz.get_tessdata())
        except Exception:
            return False

    def extract(self, page, page_number: int) -> list[ContentBlock]:
        textpage = page.get_textpage_ocr(
            flags=0,
            language=os.getenv("PDF_OCR_LANGUAGES", "chi_sim+eng"),
            dpi=300,
            full=True,
        )
        ocr_dict = page.get_text("dict", textpage=textpage, sort=False)
        layout_blocks = extract_layout_blocks_from_dict(
            ocr_dict,
            page_number=page_number,
            page_width=float(page.rect.width),
            page_height=float(page.rect.height),
            source="ocr",
            confidence=DEFAULT_OCR_CONFIDENCE,
            extraction_method="ocr",
        )
        return [block.to_content_block() for block in layout_blocks]


def _page_image_coverage(page, page_area: float) -> float:
    """Return the largest image-block coverage, bounded to the page area."""
    try:
        text_dict = page.get_text("dict", sort=False)
    except Exception:
        return 0.0
    largest_image_area = 0.0
    for block in text_dict.get("blocks", []):
        if block.get("type") != 1:
            continue
        try:
            x0, y0, x1, y1 = (float(value) for value in block["bbox"])
        except (KeyError, TypeError, ValueError):
            continue
        largest_image_area = max(
            largest_image_area,
            max(0.0, x1 - x0) * max(0.0, y1 - y0),
        )
    return min(1.0, largest_image_area / page_area)
