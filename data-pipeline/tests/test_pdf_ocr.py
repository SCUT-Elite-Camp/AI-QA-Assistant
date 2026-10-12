import sys
from pathlib import Path

import pymupdf as fitz
import pytest


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from models.document import BlockType, BoundingBox, ContentBlock  # noqa: E402
from parsers.ocr_backends import (  # noqa: E402
    OCRRegion,
    PyMuPDFOCRBackend,
    detect_ocr_regions,
    evaluate_page_text_quality,
)
from parsers import ocr_backends  # noqa: E402
from parsers.pdf_layout import LayoutBlock  # noqa: E402
from parsers.pdf_parser import PDFParser  # noqa: E402


class StaticRouter:
    def route_page(self, page, *, page_number, text_coverage, file_path=None):
        return []


class FakeOCRBackend:
    name = "fake-ocr"

    def __init__(self, blocks_by_page=None, *, available=True, error=None):
        self.blocks_by_page = blocks_by_page or {}
        self.is_available = available
        self.error = error
        self.calls = []

    def available(self):
        return self.is_available

    def extract(self, page, page_number):
        self.calls.append(page_number)
        if self.error is not None:
            raise self.error
        return self.blocks_by_page.get(page_number, [])


class FakeRegionOCRBackend(FakeOCRBackend):
    def __init__(self, blocks_by_page=None, *, available=True, error=None):
        super().__init__(blocks_by_page, available=available, error=error)
        self.region_calls = []

    def extract_regions(self, page, page_number, regions):
        self.region_calls.append((page_number, list(regions)))
        if self.error is not None:
            raise self.error
        return self.blocks_by_page.get(page_number, [])


def ocr_block(text, *, page=1, bbox=(40, 100, 460, 130), confidence=0.82):
    return ContentBlock(
        block_type=BlockType.PARAGRAPH,
        text=text,
        page_number=page,
        bbox=BoundingBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3]),
        confidence=confidence,
        source="ocr",
        extraction_method="ocr",
    )


def make_pdf(path, page_texts):
    document = fitz.open()
    for text in page_texts:
        page = document.new_page(width=500, height=600)
        if text:
            page.insert_text((60, 200), text, fontsize=12)
    document.save(path)
    document.close()


def make_mixed_pdf(path):
    document = fitz.open()
    page = document.new_page(width=500, height=600)
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False)
    image.clear_with(240)
    page.insert_image(page.rect, pixmap=image)
    page.insert_text((60, 40), "Native caption", fontsize=12)
    document.save(path)
    document.close()


def native_layout(text, bbox, *, page=1, ordinal=0):
    return LayoutBlock(
        text=text,
        bbox=bbox,
        font_size=11,
        font_name="Body",
        flags=0,
        rotation=0,
        page_number=page,
        ordinal=ordinal,
        page_width=500,
        page_height=600,
    )


def test_region_detector_targets_bad_native_without_ocring_images_on_good_page():
    page = QualityPage((40, 250, 460, 500))
    native = [
        native_layout("Reliable native paragraph", (40, 40, 300, 70)),
        native_layout("�", (50, 150, 90, 170), ordinal=1),
    ]
    quality = evaluate_page_text_quality(page, native)

    regions = detect_ocr_regions(page, native, quality)

    assert [region.bbox for region in regions] == [
        (42.0, 142.0, 98.0, 178.0),
    ]
    assert regions[0].reasons == ("unreliable_native",)


def test_region_detector_targets_image_blocks_when_page_quality_is_weak():
    page = QualityPage((40, 250, 460, 500))
    native = [native_layout("�", (50, 150, 90, 170))]
    quality = evaluate_page_text_quality(page, native)

    regions = detect_ocr_regions(page, native, quality)

    assert [region.bbox for region in regions] == [
        (42.0, 142.0, 98.0, 178.0),
        (32.0, 242.0, 468.0, 508.0),
    ]
    assert regions[1].reasons == ("image",)


def test_parser_uses_region_backend_and_persists_fusion_counts(tmp_path):
    source = tmp_path / "mixed-regions.pdf"
    make_mixed_pdf(source)
    backend = FakeRegionOCRBackend({1: [
        ocr_block("Native caption", bbox=(58, 25, 140, 46)),
        ocr_block("Scanned body recovered", bbox=(40, 100, 460, 130)),
    ]})

    document = PDFParser(router=StaticRouter(), ocr_backend=backend).parse(str(source))

    assert backend.calls == []
    assert len(backend.region_calls) == 1
    page_number, regions = backend.region_calls[0]
    assert page_number == 1
    assert regions
    assert "Scanned body recovered" in document.content
    diagnostics = document.parse_diagnostics
    assert diagnostics is not None
    assert diagnostics.ocr_candidate_regions == len(regions)
    assert diagnostics.ocr_processed_regions == len(regions)
    assert diagnostics.ocr_added_blocks == 1
    assert diagnostics.ocr_replaced_blocks == 0


def test_region_fusion_replaces_only_overlapping_unreliable_native_block(tmp_path):
    source = tmp_path / "replace-region.pdf"
    make_pdf(source, ["x"])
    backend = FakeRegionOCRBackend({1: [
        ocr_block("Recovered text", bbox=(55, 185, 180, 210)),
    ]})

    document = PDFParser(router=StaticRouter(), ocr_backend=backend).parse(str(source))

    assert document.content == "Recovered text"
    diagnostics = document.parse_diagnostics
    assert diagnostics is not None
    assert diagnostics.ocr_added_blocks == 0
    assert diagnostics.ocr_replaced_blocks == 1


def test_low_text_page_uses_injected_ocr_backend(tmp_path):
    source = tmp_path / "scan.pdf"
    make_pdf(source, [""])
    backend = FakeOCRBackend({1: [ocr_block("扫描正文")]})

    document = PDFParser(router=StaticRouter(), ocr_backend=backend).parse(str(source))

    assert backend.calls == [1]
    assert document.content == "扫描正文"
    assert len(document.content_blocks) == 1
    block = document.content_blocks[0]
    assert block.block_id == "page-1-block-0"
    assert block.source == "ocr"
    assert block.extraction_method == "ocr"
    assert block.confidence == 0.82


def test_good_native_text_does_not_run_ocr(tmp_path):
    source = tmp_path / "native.pdf"
    make_pdf(source, ["This native paragraph has enough usable text."])
    backend = FakeOCRBackend()

    document = PDFParser(router=StaticRouter(), ocr_backend=backend).parse(str(source))

    assert backend.calls == []
    assert "This native paragraph" in document.content
    assert all(block.source == "native" for block in document.content_blocks)


def test_ocr_runs_only_for_low_quality_pages_and_replaces_native_text(tmp_path):
    source = tmp_path / "mixed.pdf"
    make_pdf(source, ["A complete native paragraph with reliable extraction.", "x"])
    backend = FakeOCRBackend({2: [ocr_block("Recovered second page", page=2)]})

    document = PDFParser(router=StaticRouter(), ocr_backend=backend).parse(str(source))

    assert backend.calls == [2]
    assert "A complete native paragraph" in document.content
    assert "Recovered second page" in document.content
    assert "\n\nx\n\n" not in f"\n\n{document.content}\n\n"


def test_mixed_page_keeps_reliable_native_text_and_adds_non_overlapping_ocr(tmp_path):
    source = tmp_path / "mixed-image.pdf"
    make_mixed_pdf(source)
    backend = FakeOCRBackend({1: [
        ocr_block("Native caption", bbox=(58, 25, 140, 46)),
        ocr_block("Scanned body recovered", bbox=(40, 100, 460, 130)),
    ]})

    document = PDFParser(router=StaticRouter(), ocr_backend=backend).parse(str(source))

    assert document.content.count("Native caption") == 1
    assert "Scanned body recovered" in document.content
    caption = next(block for block in document.content_blocks if block.text == "Native caption")
    scanned = next(block for block in document.content_blocks if block.text == "Scanned body recovered")
    assert caption.source == "native"
    assert scanned.source == "ocr"
    assert [block.block_id for block in document.content_blocks] == [
        "page-1-block-0",
        "page-1-block-1",
    ]
    assert document.parse_diagnostics is not None
    assert document.parse_diagnostics.ocr_applied_pages == [1]


def test_ocr_does_not_replace_native_text_when_it_is_not_better(tmp_path):
    source = tmp_path / "not-improved.pdf"
    make_pdf(source, ["x"])
    backend = FakeOCRBackend({1: [ocr_block("?")]})
    parser = PDFParser(router=StaticRouter(), ocr_backend=backend)

    document = parser.parse(str(source))

    assert document.content == "x"
    assert parser.last_layout_diagnostics.ocr_not_improved_pages == [1]


def test_unavailable_ocr_preserves_native_text_and_records_diagnostic(tmp_path):
    source = tmp_path / "unavailable.pdf"
    make_pdf(source, ["x"])
    backend = FakeOCRBackend(available=False)
    parser = PDFParser(router=StaticRouter(), ocr_backend=backend)

    document = parser.parse(str(source))

    assert document.content == "x"
    assert backend.calls == []
    assert parser.last_layout_diagnostics.ocr_unavailable_pages == [1]


def test_ocr_exception_preserves_native_text_and_records_diagnostic(tmp_path):
    source = tmp_path / "failure.pdf"
    make_pdf(source, ["x"])
    backend = FakeOCRBackend(error=RuntimeError("language data missing"))
    parser = PDFParser(router=StaticRouter(), ocr_backend=backend)

    document = parser.parse(str(source))

    assert document.content == "x"
    assert backend.calls == [1]
    assert parser.last_layout_diagnostics.ocr_failed_pages == [1]
    assert "language data missing" in parser.last_layout_diagnostics.ocr_messages[0]
    assert document.parse_diagnostics is not None
    assert document.parse_diagnostics.ocr_failed_pages == [1]
    assert "language data missing" in document.parse_diagnostics.ocr_messages[0]


def test_ocr_blocks_use_shared_header_filter_and_reading_order(tmp_path):
    source = tmp_path / "ordered.pdf"
    make_pdf(source, ["", ""])
    backend = FakeOCRBackend({
        1: [
            ocr_block("Repeated report", page=1, bbox=(40, 15, 460, 35)),
            ocr_block("right 1", page=1, bbox=(300, 100, 460, 125)),
            ocr_block("left 2", page=1, bbox=(40, 150, 200, 175)),
            ocr_block("right 2", page=1, bbox=(300, 150, 460, 175)),
            ocr_block("left 1", page=1, bbox=(40, 100, 200, 125)),
        ],
        2: [
            ocr_block("Repeated report", page=2, bbox=(40, 15, 460, 35)),
            ocr_block("second page body", page=2, bbox=(40, 100, 300, 125)),
        ],
    })
    parser = PDFParser(router=StaticRouter(), ocr_backend=backend)

    document = parser.parse(str(source))

    assert "Repeated report" not in document.content
    assert document.content.index("left 2") < document.content.index("right 1")
    assert parser.last_layout_diagnostics.removed_headers == 2
    assert document.parse_diagnostics is not None
    assert document.parse_diagnostics.removed_headers == 2
    assert document.parse_diagnostics.ocr_applied_pages == [1, 2]


class FakeRect:
    width = 500
    height = 600


class RecordingOCRPage:
    rect = FakeRect()

    def __init__(self):
        self.calls = []

    def get_textpage_ocr(self, **kwargs):
        self.calls.append(("ocr", kwargs))
        return "textpage"

    def get_text(self, kind, **kwargs):
        self.calls.append(("text", kind, kwargs))
        return {
            "blocks": [{
                "type": 0,
                "bbox": (40, 100, 300, 130),
                "lines": [{
                    "dir": (1, 0),
                    "spans": [{
                        "text": "OCR result",
                        "size": 11,
                        "font": "OCRFont",
                        "flags": 0,
                    }],
                }],
            }],
        }


class QualityPage:
    rect = FakeRect()

    def __init__(self, image_bbox=None):
        self.image_bbox = image_bbox

    def get_text(self, kind, **kwargs):
        assert kind == "dict"
        blocks = []
        if self.image_bbox is not None:
            blocks.append({"type": 1, "bbox": self.image_bbox})
        return {"blocks": blocks}


def native_block(text):
    return ContentBlock(block_type=BlockType.PARAGRAPH, text=text)


def test_page_quality_detects_sparse_invalid_and_image_dominated_pages():
    good = evaluate_page_text_quality(
        QualityPage(), [native_block("This is a complete, readable native paragraph.")]
    )
    sparse = evaluate_page_text_quality(QualityPage(), [native_block("x")])
    garbled = evaluate_page_text_quality(QualityPage(), [native_block("abc���")])
    image_dominated = evaluate_page_text_quality(
        QualityPage((0, 0, 500, 600)), [native_block("short caption")]
    )

    assert good.needs_ocr is False
    assert good.usable_character_count == 40
    assert sparse.needs_ocr is True
    assert "sparse_text" in sparse.reasons
    assert garbled.needs_ocr is True
    assert garbled.replacement_character_ratio == 0.5
    assert "replacement_characters" in garbled.reasons
    assert image_dominated.needs_ocr is True
    assert image_dominated.page_image_coverage == 1.0
    assert "image_dominated" in image_dominated.reasons


def test_pymupdf_backend_converts_ocr_dict_to_provenance_blocks(monkeypatch):
    monkeypatch.setenv("PDF_OCR_LANGUAGES", "eng")
    page = RecordingOCRPage()
    blocks = PyMuPDFOCRBackend().extract(page, page_number=3)

    assert page.calls[0] == ("ocr", {"flags": 0, "language": "eng", "dpi": 300, "full": True})
    assert page.calls[1] == ("text", "dict", {"textpage": "textpage", "sort": False})
    assert len(blocks) == 1
    assert blocks[0].block_id == "page-3-block-0"
    assert blocks[0].page_number == 3
    assert blocks[0].bbox == BoundingBox(x0=40, y0=100, x1=300, y1=130)
    assert blocks[0].source == "ocr"
    assert blocks[0].extraction_method == "ocr"
    assert blocks[0].confidence < 1.0


def test_pymupdf_backend_crops_regions_and_maps_ocr_boxes_to_page(monkeypatch):
    class RegionPixmap:
        def __init__(self):
            self.calls = []

        def pdfocr_tobytes(self, **kwargs):
            self.calls.append(kwargs)
            return b"ocr-pdf"

    class SourcePage:
        rect = fitz.Rect(0, 0, 500, 600)

        def __init__(self):
            self.calls = []
            self.pixmap = RegionPixmap()

        def get_pixmap(self, **kwargs):
            self.calls.append(kwargs)
            return self.pixmap

    class OCRPage:
        rect = fitz.Rect(0, 0, 200, 100)

        def get_text(self, kind, *, sort):
            assert (kind, sort) == ("dict", False)
            return {"blocks": [{
                "type": 0,
                "bbox": (20, 10, 180, 90),
                "lines": [{
                    "dir": (1, 0),
                    "spans": [{
                        "text": "Regional OCR",
                        "size": 10,
                        "font": "OCRFont",
                        "flags": 0,
                    }],
                }],
            }]}

    class OCRDocument:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __getitem__(self, index):
            assert index == 0
            return OCRPage()

    monkeypatch.setattr(ocr_backends.fitz, "open", lambda **kwargs: OCRDocument())
    backend = PyMuPDFOCRBackend()
    backend._installed_languages_cache = ("eng",)
    page = SourcePage()

    blocks = backend.extract_regions(
        page,
        page_number=2,
        regions=[OCRRegion((100, 200, 300, 300), ("image",))],
    )

    assert tuple(page.calls[0]["clip"]) == (100.0, 200.0, 300.0, 300.0)
    assert page.calls[0]["dpi"] == 300
    assert page.pixmap.calls == [{"compress": False, "language": "eng"}]
    assert len(blocks) == 1
    assert blocks[0].text == "Regional OCR"
    assert blocks[0].page_number == 2
    assert blocks[0].bbox == BoundingBox(x0=120, y0=210, x1=280, y1=290)
    assert blocks[0].extraction_method == "ocr-region"


def test_pymupdf_backend_falls_back_to_installed_english_and_uses_configured_dpi(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "eng.traineddata").write_bytes(b"language")
    monkeypatch.setattr(fitz, "get_tessdata", lambda: str(tmp_path))
    monkeypatch.delenv("PDF_OCR_LANGUAGES", raising=False)
    monkeypatch.setenv("PDF_OCR_DPI", "220")
    page = RecordingOCRPage()
    backend = PyMuPDFOCRBackend()

    assert backend.available() is True
    backend.extract(page, page_number=1)

    assert page.calls[0][1]["language"] == "eng"
    assert page.calls[0][1]["dpi"] == 220


def test_pymupdf_backend_is_unavailable_when_tessdata_has_no_languages(tmp_path, monkeypatch):
    monkeypatch.setattr(fitz, "get_tessdata", lambda: str(tmp_path))

    assert PyMuPDFOCRBackend().available() is False


@pytest.mark.parametrize("configured", ["not-a-number", "71", "601"])
def test_pymupdf_backend_rejects_invalid_dpi(configured, monkeypatch):
    monkeypatch.setenv("PDF_OCR_LANGUAGES", "eng")
    monkeypatch.setenv("PDF_OCR_DPI", configured)
    page = RecordingOCRPage()

    PyMuPDFOCRBackend().extract(page, page_number=1)

    assert page.calls[0][1]["dpi"] == 300
