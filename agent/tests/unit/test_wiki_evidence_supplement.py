import pytest

from agent.evidence import EvidenceGate, WikiEvidenceSupplementer
from agent.schemas.tool_execution import Evidence


pytestmark = pytest.mark.no_storage


def _evidence(
    index: int,
    *,
    source_scope: str = "enterprise",
    document_id: str | None = None,
    version_id: str | None = "version-1",
    chunk_id: str | None = None,
    score: float = 0.9,
) -> Evidence:
    doc_id = document_id or f"doc-{index}"
    return Evidence(
        doc_id=doc_id,
        document_id=doc_id,
        version_id=version_id,
        source_scope=source_scope,
        chunk_id=chunk_id or f"chunk-{index}",
        title=f"Document {index}",
        content=f"Evidence {index}",
        score=score,
        retrieval_query="query",
        retrieval_mode="hybrid",
    )


def _supplementer(*, wiki_top_k: int = 3) -> WikiEvidenceSupplementer:
    return WikiEvidenceSupplementer(
        evidence_gate=EvidenceGate(min_score=0.5),
        wiki_top_k=wiki_top_k,
    )


def test_direct_five_and_wiki_three_produce_eight_unique_evidence() -> None:
    direct = [_evidence(index) for index in range(5)]
    result = _supplementer().supplement(
        direct,
        [_evidence(index + 100) for index in range(3)],
    )

    assert result.evidence[:5] == direct
    assert len(result.evidence) == 8
    assert result.wiki_selected == 3


def test_wiki_is_appended_without_displacing_twenty_direct_items() -> None:
    direct = [_evidence(index) for index in range(20)]
    result = _supplementer().supplement(
        direct,
        [_evidence(index + 100) for index in range(5)],
    )

    assert result.evidence[:20] == direct
    assert len(result.evidence) == 23
    assert result.wiki_selected == 3


def test_direct_duplicate_does_not_consume_wiki_quota() -> None:
    duplicate = _evidence(1)
    result = _supplementer().supplement(
        [duplicate, _evidence(2)],
        [
            duplicate.model_copy(update={"score": 0.99}),
            _evidence(101),
            _evidence(102),
            _evidence(103),
        ],
    )

    assert result.wiki_selected == 3
    assert result.wiki_duplicates_skipped == 1
    assert [item.doc_id for item in result.evidence[-3:]] == [
        "doc-101", "doc-102", "doc-103",
    ]


def test_incomplete_direct_identity_still_blocks_the_same_wiki_chunk() -> None:
    direct = _evidence(1).model_copy(update={
        "source_scope": None,
        "version_id": None,
    })
    duplicate = _evidence(1, version_id="version-2")

    result = _supplementer(wiki_top_k=1).supplement(
        [direct],
        [duplicate, _evidence(2)],
    )

    assert [item.doc_id for item in result.evidence] == ["doc-1", "doc-2"]
    assert result.wiki_duplicates_skipped == 1


def test_low_score_direct_does_not_block_eligible_wiki_replacement() -> None:
    result = _supplementer(wiki_top_k=1).supplement(
        [_evidence(1, score=0.49)],
        [_evidence(1, score=0.9)],
    )

    assert len(result.evidence) == 2
    assert result.wiki_selected == 1
    assert result.wiki_duplicates_skipped == 0


def test_low_score_and_unversioned_wiki_candidates_are_replaced() -> None:
    result = _supplementer().supplement(
        [_evidence(1)],
        [
            _evidence(101, score=0.49),
            _evidence(102, version_id=None),
            _evidence(103),
            _evidence(104),
            _evidence(105),
        ],
    )

    assert [item.doc_id for item in result.evidence[-3:]] == [
        "doc-103", "doc-104", "doc-105",
    ]


def test_zero_wiki_quota_returns_only_direct_evidence() -> None:
    direct = [_evidence(1), _evidence(2)]
    result = _supplementer(wiki_top_k=0).supplement(
        direct,
        [_evidence(101)],
    )

    assert result.evidence == direct
    assert result.wiki_selected == 0
