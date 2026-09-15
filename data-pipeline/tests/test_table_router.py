import sys
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from models.document import BoundingBox, TableArtifact, TableCell  # noqa: E402
from parsers.table_router import (  # noqa: E402
    TableQualityScorer,
    TableRouter,
    TableRouterConfig,
)


def make_table(parser_name, confidence, values=("字段", "10"), bbox=(0, 0, 100, 50)):
    return TableArtifact(
        table_id=f"{parser_name}-1",
        cells=[
            TableCell(row_index=0, column_index=0, text=values[0], is_header=True),
            TableCell(row_index=1, column_index=0, text=values[1]),
        ],
        row_count=2,
        column_count=1,
        header_row_count=1,
        bbox=BoundingBox(x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3]),
        parser_name=parser_name,
        confidence=confidence,
    )


class FakeBackend:
    def __init__(self, name, artifacts=None, available=True, error=None):
        self.name = name
        self.artifacts = artifacts or []
        self.is_available = available
        self.error = error
        self.calls = 0

    def available(self):
        return self.is_available

    def extract(self, page, page_number, file_path=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.artifacts


def test_router_stops_after_accepted_fast_path():
    primary = FakeBackend("pymupdf", [make_table("pymupdf", 0.95)])
    camelot = FakeBackend("camelot", [make_table("camelot", 0.99)])
    paddle = FakeBackend("paddle", [make_table("paddle", 0.99)])
    router = TableRouter(primary, camelot, paddle)

    result = router.route_page(object(), page_number=1, text_coverage=0.8)

    assert [table.parser_name for table in result] == ["pymupdf"]
    assert primary.calls == 1
    assert camelot.calls == 0
    assert paddle.calls == 0


def test_router_escalates_low_score_and_selects_better_candidate():
    primary = FakeBackend("pymupdf", [make_table("pymupdf", 0.2)])
    camelot = FakeBackend("camelot", [make_table("camelot", 0.96)])
    paddle = FakeBackend("paddle", [make_table("paddle", 0.99)])
    router = TableRouter(primary, camelot, paddle)

    result = router.route_page(object(), page_number=1, text_coverage=0.8)

    assert len(result) == 1
    assert result[0].parser_name == "camelot"
    assert camelot.calls == 1
    assert paddle.calls == 0


def test_router_uses_complex_electronic_fallback_before_ocr():
    primary = FakeBackend("pymupdf", [make_table("pymupdf", 0.2)])
    camelot = FakeBackend("camelot", [make_table("camelot", 0.3)])
    gmft = FakeBackend("gmft", [make_table("gmft", 0.97)])
    paddle = FakeBackend("paddle", [make_table("paddle", 0.99)])
    router = TableRouter(primary, camelot, paddle, complex_fallback=gmft)

    result = router.route_page(object(), page_number=1, text_coverage=0.8)

    assert len(result) == 1
    assert result[0].parser_name == "gmft"
    assert gmft.calls == 1
    assert paddle.calls == 0
    assert result[0].backend_confidence == 0.97
    assert result[0].quality_score is not None
    assert result[0].acceptance == "accepted"


def test_router_records_optional_backend_failure_without_losing_candidate():
    primary = FakeBackend("pymupdf", [make_table("pymupdf", 0.3)])
    camelot = FakeBackend("camelot", available=False)
    paddle = FakeBackend("paddle", error=RuntimeError("model missing"))
    router = TableRouter(
        primary,
        camelot,
        paddle,
        config=TableRouterConfig(paddle_threshold=0.9),
    )

    result = router.route_page(object(), page_number=1, text_coverage=0.01)

    assert len(result) == 1
    assert result[0].parser_name == "pymupdf"
    assert "backend_unavailable:camelot" in result[0].warnings
    assert "backend_error:paddle" in result[0].warnings


def test_router_marks_numeric_conflict_between_overlapping_candidates():
    primary = FakeBackend("pymupdf", [make_table("pymupdf", 0.4, values=("金额", "10"))])
    camelot = FakeBackend("camelot", [make_table("camelot", 0.9, values=("金额", "18"))])
    router = TableRouter(primary, camelot, None)

    result = router.route_page(object(), page_number=1, text_coverage=0.8)

    assert len(result) == 1
    assert result[0].parser_name == "camelot"
    assert "numeric_disagreement" in result[0].warnings


def test_quality_scorer_penalizes_sparse_non_rectangular_candidate():
    scorer = TableQualityScorer()
    complete = TableArtifact(
        table_id="complete",
        cells=[
            TableCell(row_index=0, column_index=0, text="A", is_header=True),
            TableCell(row_index=0, column_index=1, text="B", is_header=True),
            TableCell(row_index=1, column_index=0, text="1"),
            TableCell(row_index=1, column_index=1, text="2"),
        ],
        row_count=2,
        column_count=2,
        header_row_count=1,
        parser_name="test",
        confidence=0.5,
    )
    sparse = TableArtifact(
        table_id="sparse",
        cells=[TableCell(row_index=0, column_index=0, text="A")],
        row_count=3,
        column_count=3,
        parser_name="test",
        confidence=0.5,
    )

    assert scorer.score(complete) > scorer.score(sparse)
    assert scorer.score(complete) >= 0.7
    evidence = scorer.evaluate(complete)
    assert evidence.score == scorer.score(complete)
    assert evidence.features["non_empty_ratio"] == 1.0
    assert evidence.features["rectangularity"] == 1.0


def test_router_rejects_candidate_below_final_quality_floor():
    sparse = TableArtifact(
        table_id="false-positive",
        cells=[TableCell(row_index=0, column_index=0, text="border")],
        row_count=3,
        column_count=3,
        parser_name="pymupdf",
        confidence=0.1,
    )
    router = TableRouter(FakeBackend("pymupdf", [sparse]))

    result = router.route_page(object(), page_number=1, text_coverage=0.9)

    assert result == []
