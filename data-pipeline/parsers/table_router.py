"""Quality scoring, fallback routing, and reconciliation for table backends."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from models.document import BoundingBox, TableArtifact


class TableBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def extract(
        self,
        page: Any,
        page_number: int,
        file_path: str | None = None,
    ) -> list[TableArtifact]: ...


@dataclass(frozen=True)
class TableRouterConfig:
    accept_confidence: float = 0.78
    camelot_ml_threshold: float = 0.65
    paddle_threshold: float = 0.55
    scan_text_coverage_threshold: float = 0.08
    candidate_iou_threshold: float = 0.50


@dataclass(frozen=True)
class TableQualityEvidence:
    score: float
    features: dict[str, float]


class TableQualityScorer:
    """Compute an explainable structural quality score in the range [0, 1]."""

    def score(self, artifact: TableArtifact) -> float:
        return self.evaluate(artifact).score

    def evaluate(self, artifact: TableArtifact) -> TableQualityEvidence:
        total_slots = max(1, artifact.row_count * artifact.column_count)
        matrix = artifact.to_matrix()
        non_empty = sum(1 for row in matrix for value in row if value.strip())
        non_empty_ratio = non_empty / total_slots

        covered = set()
        valid_spans = 0
        for cell in artifact.cells:
            span_is_valid = (
                cell.row_index + cell.row_span <= artifact.row_count
                and cell.column_index + cell.column_span <= artifact.column_count
            )
            if span_is_valid:
                valid_spans += 1
            for row in range(cell.row_index, cell.row_index + cell.row_span):
                for column in range(cell.column_index, cell.column_index + cell.column_span):
                    if row < artifact.row_count and column < artifact.column_count:
                        covered.add((row, column))
        rectangularity = len(covered) / total_slots
        span_consistency = valid_spans / max(1, len(artifact.cells))

        if artifact.header_row_count == 0:
            header_quality = 0.5
        else:
            header_values = [value for row in artifact.header_rows() for value in row]
            header_quality = sum(bool(value.strip()) for value in header_values) / max(1, len(header_values))

        backend_confidence = (
            artifact.backend_confidence
            if artifact.backend_confidence is not None
            else artifact.confidence
        )
        features = {
            "non_empty_ratio": round(non_empty_ratio, 4),
            "rectangularity": round(rectangularity, 4),
            "span_consistency": round(span_consistency, 4),
            "header_quality": round(header_quality, 4),
            "backend_confidence": round(backend_confidence, 4),
        }
        score = (
            0.30 * non_empty_ratio
            + 0.25 * rectangularity
            + 0.20 * span_consistency
            + 0.15 * header_quality
            + 0.10 * backend_confidence
        )
        return TableQualityEvidence(
            score=round(max(0.0, min(1.0, score)), 4),
            features=features,
        )


class TableRouter:
    def __init__(
        self,
        primary: TableBackend,
        electronic_fallback: TableBackend | None = None,
        ocr_fallback: TableBackend | None = None,
        *,
        complex_fallback: TableBackend | None = None,
        scorer: TableQualityScorer | None = None,
        config: TableRouterConfig | None = None,
    ) -> None:
        self.primary = primary
        self.electronic_fallback = electronic_fallback
        self.ocr_fallback = ocr_fallback
        self.complex_fallback = complex_fallback
        self.scorer = scorer or TableQualityScorer()
        self.config = config or TableRouterConfig()
        self.last_diagnostics: list[str] = []

    def route_page(
        self,
        page: Any,
        *,
        page_number: int,
        text_coverage: float,
        file_path: str | None = None,
    ) -> list[TableArtifact]:
        self.last_diagnostics = []
        candidates = self._run_backend(self.primary, page, page_number, file_path, required=True)
        original_confidences = {id(item): item.confidence for item in candidates}

        if self._accepted(candidates, original_confidences):
            return self._finalize(candidates)

        fallback = self.electronic_fallback
        if fallback is not None:
            more = self._run_backend(fallback, page, page_number, file_path)
            candidates.extend(more)
            original_confidences.update({id(item): item.confidence for item in more})

        if self._accepted(candidates, original_confidences):
            return self._finalize(candidates)

        if self.complex_fallback is not None:
            should_run = getattr(self.complex_fallback, "should_run", None)
            if should_run is None or should_run(page):
                more = self._run_backend(self.complex_fallback, page, page_number, file_path)
                candidates.extend(more)
                original_confidences.update({id(item): item.confidence for item in more})
            else:
                self.last_diagnostics.append(
                    f"backend_skipped:{self.complex_fallback.name}:no_table_signal"
                )

        if self._accepted(candidates, original_confidences):
            return self._finalize(candidates)

        best_original = max(original_confidences.values(), default=0.0)
        needs_ocr = (
            text_coverage < self.config.scan_text_coverage_threshold
            or best_original < self.config.paddle_threshold
        )
        if needs_ocr and self.ocr_fallback is not None:
            more = self._run_backend(self.ocr_fallback, page, page_number, file_path)
            candidates.extend(more)
            original_confidences.update({id(item): item.confidence for item in more})

        return self._finalize(candidates)

    def _accepted(
        self,
        candidates: list[TableArtifact],
        original_confidences: dict[int, float],
    ) -> bool:
        return any(
            self.scorer.score(candidate) >= self.config.accept_confidence
            and original_confidences.get(id(candidate), candidate.confidence)
            >= self.config.camelot_ml_threshold
            for candidate in candidates
        )

    def _run_backend(
        self,
        backend: TableBackend,
        page: Any,
        page_number: int,
        file_path: str | None,
        *,
        required: bool = False,
    ) -> list[TableArtifact]:
        try:
            if not backend.available():
                diagnostic = f"backend_unavailable:{backend.name}"
                self.last_diagnostics.append(diagnostic)
                return []
            return backend.extract(page, page_number, file_path)
        except Exception:
            diagnostic = f"backend_error:{backend.name}"
            self.last_diagnostics.append(diagnostic)
            if required:
                return []
            return []

    def _finalize(self, candidates: list[TableArtifact]) -> list[TableArtifact]:
        if not candidates:
            return []
        scored = []
        for candidate in candidates:
            evidence = self.scorer.evaluate(candidate)
            if evidence.score >= self.config.paddle_threshold:
                acceptance = (
                    "accepted"
                    if (
                        evidence.score >= self.config.accept_confidence
                        and evidence.features["backend_confidence"]
                        >= self.config.camelot_ml_threshold
                    )
                    else "review"
                )
                warnings = list(candidate.warnings)
                if acceptance == "review":
                    warnings.append("needs_review")
                scored.append(candidate.model_copy(update={
                    "confidence": evidence.score,
                    "backend_confidence": (
                        candidate.backend_confidence
                        if candidate.backend_confidence is not None
                        else candidate.confidence
                    ),
                    "quality_score": evidence.score,
                    "quality_evidence": evidence.features,
                    "acceptance": acceptance,
                    "warnings": _unique(warnings),
                }))
        if not scored:
            return []
        reconciled = self._reconcile(scored)
        if self.last_diagnostics:
            reconciled = [
                table.model_copy(
                    update={"warnings": _unique(table.warnings + self.last_diagnostics)}
                )
                for table in reconciled
            ]
        return sorted(
            reconciled,
            key=lambda table: (
                table.page_number or 0,
                table.bbox.y0 if table.bbox else 0,
                table.bbox.x0 if table.bbox else 0,
            ),
        )

    def _reconcile(self, candidates: list[TableArtifact]) -> list[TableArtifact]:
        groups: list[list[TableArtifact]] = []
        for candidate in candidates:
            for group in groups:
                if _same_table(candidate, group[0], self.config.candidate_iou_threshold):
                    group.append(candidate)
                    break
            else:
                groups.append([candidate])

        results: list[TableArtifact] = []
        for group in groups:
            selected = max(group, key=lambda item: item.quality_score or item.confidence)
            warnings = list(selected.warnings)
            if len(group) > 1 and _numeric_sets_disagree(group):
                warnings.append("numeric_disagreement")
            if len(group) > 1 and _shapes_disagree(group):
                warnings.append("shape_disagreement")
            if len(group) > 1 and _headers_disagree(group):
                warnings.append("header_disagreement")
            selected = selected.model_copy(update={"warnings": _unique(warnings)})
            results.append(selected)
        return results


def _same_table(left: TableArtifact, right: TableArtifact, threshold: float) -> bool:
    if left.page_number != right.page_number:
        return False
    if left.bbox is None or right.bbox is None:
        return left.table_id == right.table_id
    return _bbox_iou(left.bbox, right.bbox) >= threshold


def _bbox_iou(left: BoundingBox, right: BoundingBox) -> float:
    x0 = max(left.x0, right.x0)
    y0 = max(left.y0, right.y0)
    x1 = min(left.x1, right.x1)
    y1 = min(left.y1, right.y1)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    left_area = max(0.0, left.x1 - left.x0) * max(0.0, left.y1 - left.y0)
    right_area = max(0.0, right.x1 - right.x0) * max(0.0, right.y1 - right.y0)
    union = left_area + right_area - intersection
    return intersection / union if union else 0.0


def _numeric_sets_disagree(candidates: list[TableArtifact]) -> bool:
    numeric_sets = []
    for candidate in candidates:
        values = " ".join(value for row in candidate.to_matrix() for value in row)
        numeric_sets.append(set(re.findall(r"[-+]?\d+(?:[.,]\d+)*%?", values)))
    return any(values != numeric_sets[0] for values in numeric_sets[1:])


def _shapes_disagree(candidates: list[TableArtifact]) -> bool:
    shapes = {(candidate.row_count, candidate.column_count) for candidate in candidates}
    return len(shapes) > 1


def _headers_disagree(candidates: list[TableArtifact]) -> bool:
    headers = {tuple(value.casefold() for value in candidate.legacy_headers()) for candidate in candidates}
    return len(headers) > 1


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
