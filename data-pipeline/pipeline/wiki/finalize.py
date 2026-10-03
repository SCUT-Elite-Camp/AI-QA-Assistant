"""Deterministic finalization after Claim audit and before atomic publication."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from .domain import RevisionStatus, WikiIdentity, WikiPageDraft, WikiPageType, stable_id
from .linkify import linkify_pages


_WIKI_LINK = re.compile(r"\[([^\]]+)\]\(/wiki/([^\)]+)\)")


def finalize_wiki_pages(
    pages: Iterable[WikiPageDraft], identities: Iterable[WikiIdentity],
) -> list[WikiPageDraft]:
    values = linkify_pages(
        [page for page in pages if page.page_type != WikiPageType.INDEX], identities,
    )
    if not values:
        return []
    page_ids = {page.id for page in values}
    valid_slugs = {page.slug for page in values}
    for page in values:
        page.links = sorted(target for target in set(page.links) if target in page_ids and target != page.id)
        page.summary = _remove_dead_links(page.summary, valid_slugs)
        for section in page.sections:
            for claim in section.claims:
                claim.rendered_text = _remove_dead_links(claim.rendered_text, valid_slugs)
    values.append(_compile_index(values[0], values))
    return values


def _remove_dead_links(text: str, valid_slugs: set[str]) -> str:
    return _WIKI_LINK.sub(
        lambda match: match.group(0) if match.group(2) in valid_slugs else match.group(1), text,
    )


def _compile_index(seed: WikiPageDraft, pages: list[WikiPageDraft]) -> WikiPageDraft:
    targets = sorted(pages, key=lambda page: (page.page_type.value, page.title.casefold(), page.id))
    page_id = stable_id(
        "wp", seed.scope.source_scope, seed.scope.owner_id, seed.scope.knowledge_base_id, "index",
    )
    input_hash = hashlib.sha256("\n".join(page.input_hash for page in targets).encode("utf-8")).hexdigest()
    return WikiPageDraft(
        id=page_id, scope=seed.scope, page_type=WikiPageType.INDEX, slug="index",
        title="Knowledge Index", summary="Navigation index for published Wiki pages.",
        sections=[], links=[page.id for page in targets], generator_model="deterministic",
        prompt_version="wiki-finalize-v1", input_hash=input_hash,
        status=RevisionStatus.REVIEWING,
    )
