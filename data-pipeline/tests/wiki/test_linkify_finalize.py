from __future__ import annotations

from pipeline.wiki.domain import (
    CandidateKind, WikiClaim, WikiIdentity, WikiPageDraft, WikiPageType,
    WikiScope, WikiSectionDraft,
)
from pipeline.wiki.finalize import finalize_wiki_pages


def test_finalize_linkifies_once_skips_markdown_and_removes_dead_links() -> None:
    scope = WikiScope(source_scope="enterprise", knowledge_base_id="kb")
    identity = WikiIdentity(
        id="identity-rag", scope=scope, kind=CandidateKind.CONCEPT,
        canonical_name="Retrieval Augmented Generation", aliases=["RAG"],
        slug="retrieval-augmented-generation-12345678",
        candidate_ids=["candidate"], source_ids=["source"],
    )
    identity_page = WikiPageDraft(
        id="page-rag", scope=scope, page_type=WikiPageType.CONCEPT,
        slug=identity.slug, title=identity.canonical_name, identity_id=identity.id,
        input_hash="identity-hash",
    )
    summary = WikiPageDraft(
        id="page-summary", scope=scope, page_type=WikiPageType.SUMMARY,
        slug="summary", title="Summary", input_hash="summary-hash",
        summary="中文RAG系统 overview; `RAG code`; [RAG existing](https://example.test).",
        links=["missing-page"],
        sections=[WikiSectionDraft(heading="Overview", claims=[WikiClaim(
            id="claim", text="RAG appears again and [dead](/wiki/missing).", source_ids=["source"],
        )])],
    )
    pages = finalize_wiki_pages([identity_page, summary], [identity])
    final_summary = next(page for page in pages if page.id == summary.id)
    index = next(page for page in pages if page.page_type == WikiPageType.INDEX)
    assert "中文[RAG](/wiki/retrieval-augmented-generation-12345678)系统" in final_summary.summary
    assert "`RAG code`" in final_summary.summary
    assert "[RAG existing](https://example.test)" in final_summary.summary
    claim = final_summary.sections[0].claims[0]
    assert claim.text == "RAG appears again and [dead](/wiki/missing)."
    assert "/wiki/missing" not in claim.rendered_text
    assert final_summary.links == [identity_page.id]
    assert index.links == [identity_page.id, summary.id]
    assert finalize_wiki_pages(pages, [identity]) == pages
