"""Deterministic Wiki link insertion over finalized page prose."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .domain import WikiIdentity, WikiPageDraft, WikiPageType


_PROTECTED_MARKDOWN = re.compile(
    r"```[\s\S]*?```|`[^`\n]*`|!?\[[^\]\n]*\]\([^\)\n]+\)", re.MULTILINE,
)
_WIKI_LINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(/wiki/([^\)\n]+)\)")


@dataclass(frozen=True)
class _LinkTarget:
    name: str
    page_id: str
    slug: str


def linkify_pages(
    pages: Iterable[WikiPageDraft], identities: Iterable[WikiIdentity],
) -> list[WikiPageDraft]:
    values = [page.model_copy(deep=True) for page in pages]
    page_by_identity = {
        page.identity_id: page
        for page in values
        if page.identity_id and page.page_type in {WikiPageType.ENTITY, WikiPageType.CONCEPT}
    }
    targets: list[_LinkTarget] = []
    for identity in identities:
        target_page = page_by_identity.get(identity.id)
        if target_page is None:
            continue
        for name in {identity.canonical_name, *identity.aliases}:
            clean = " ".join(name.split())
            if len(clean) >= 2:
                targets.append(_LinkTarget(clean, target_page.id, target_page.slug))
    targets.sort(key=lambda item: (-len(item.name), item.name.casefold(), item.page_id))

    for page in values:
        if page.page_type not in {WikiPageType.SUMMARY, WikiPageType.ENTITY, WikiPageType.CONCEPT}:
            continue
        slug_to_page = {target.slug: target.page_id for target in targets}
        source_texts = [page.summary, *(
            claim.text for section in page.sections for claim in section.claims
        )]
        used = {
            slug_to_page[match.group(1)]
            for prose in source_texts for match in _WIKI_LINK.finditer(prose)
            if match.group(1) in slug_to_page
        }
        page.summary = _link_markdown(page.summary, targets, used, page.id)
        for section in page.sections:
            for claim in section.claims:
                claim.rendered_text = _link_markdown(claim.text, targets, used, page.id)
        page.links = sorted(used)
    return values


def _link_markdown(
    text: str, targets: list[_LinkTarget], used: set[str], self_page_id: str,
) -> str:
    if not text:
        return text
    result: list[str] = []
    cursor = 0
    for match in _PROTECTED_MARKDOWN.finditer(text):
        result.append(_link_plain(text[cursor:match.start()], targets, used, self_page_id))
        result.append(match.group(0))
        cursor = match.end()
    result.append(_link_plain(text[cursor:], targets, used, self_page_id))
    return "".join(result)


def _link_plain(
    text: str, targets: list[_LinkTarget], used: set[str], self_page_id: str,
) -> str:
    matches: list[tuple[int, int, _LinkTarget]] = []
    for target in targets:
        if target.page_id == self_page_id or target.page_id in used:
            continue
        for match in re.finditer(re.escape(target.name), text, flags=re.IGNORECASE):
            start, end = match.span()
            if target.name.isascii():
                if start and _is_ascii_word_char(text[start - 1]):
                    continue
                if end < len(text) and _is_ascii_word_char(text[end]):
                    continue
            matches.append((start, end, target))
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2].page_id))
    selected: list[tuple[int, int, _LinkTarget]] = []
    occupied_until = -1
    for start, end, target in matches:
        if start < occupied_until or target.page_id in used:
            continue
        selected.append((start, end, target))
        used.add(target.page_id)
        occupied_until = end
    if not selected:
        return text
    result: list[str] = []
    cursor = 0
    for start, end, target in selected:
        result.extend([text[cursor:start], f"[{text[start:end]}](/wiki/{target.slug})"])
        cursor = end
    result.append(text[cursor:])
    return "".join(result)


def _is_ascii_word_char(value: str) -> bool:
    return value.isascii() and (value.isalnum() or value == "_")
