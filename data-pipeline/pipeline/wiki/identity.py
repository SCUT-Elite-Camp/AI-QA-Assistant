"""Conservative same-kind identity resolution with immutable identities."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any, Iterable

from .domain import (
    CandidateKind,
    CandidateStatus,
    WikiCandidate,
    WikiIdentity,
    WikiIssue,
    normalize_name,
    source_reference_id,
    stable_id,
    stable_slug,
)
from .extraction import JsonCompletionClient


IDENTITY_PROMPT_VERSION = "wiki-identity-resolution-v2"

_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": ["NEW", "MERGE"]},
        "target_identity_id": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
    "required": ["action", "target_identity_id", "reason"],
}

_TYPE_CONFLICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["ENTITY", "CONCEPT", "UNRESOLVED"]},
        "reason": {"type": "string"},
    },
    "required": ["kind", "reason"],
}


class IdentityResolver:
    """Resolve aliases as identity, never mere relatedness or topical similarity."""

    def __init__(self, client: JsonCompletionClient, *, max_targets: int = 5) -> None:
        if not 1 <= max_targets <= 5:
            raise ValueError("identity target bound must be between one and five")
        self.client = client
        self.max_targets = max_targets

    def resolve(
        self,
        candidates: Iterable[WikiCandidate],
        *,
        existing: Iterable[WikiIdentity] = (),
    ) -> list[WikiIdentity]:
        identities, _ = self.resolve_with_issues(candidates, existing=existing)
        return identities

    def resolve_with_issues(
        self,
        candidates: Iterable[WikiCandidate],
        *,
        existing: Iterable[WikiIdentity] = (),
    ) -> tuple[list[WikiIdentity], list[WikiIssue]]:
        accepted = sorted(
            (item for item in candidates if item.status == CandidateStatus.EVIDENCE_BOUND),
            key=lambda item: (item.kind.value, normalize_name(item.name), item.id),
        )
        existing_values = [item.model_copy(deep=True) for item in existing]
        if not accepted:
            return existing_values, []
        scope = accepted[0].scope
        if any(item.scope != scope for item in accepted) or any(item.scope != scope for item in existing_values):
            raise ValueError("identity resolution cannot cross Wiki scopes")
        if len({item.id for item in existing_values}) != len(existing_values):
            raise ValueError("existing Wiki identity IDs must be unique")

        original_candidate_ids = {item.id for item in accepted}
        accepted, conflict_issues = self._resolve_type_conflicts(accepted)
        quarantined_ids = original_candidate_ids - {item.id for item in accepted}
        identities = _retain_existing(existing_values, accepted, quarantined_ids)

        represented = {candidate_id for item in identities for candidate_id in item.candidate_ids}
        for candidate in accepted:
            if candidate.id in represented:
                continue
            exact = _exact_identity(candidate, identities)
            if exact is not None:
                _merge_candidate(exact, candidate)
                continue
            targets = _lexical_targets(candidate, identities, self.max_targets)
            target = self._choose_target(candidate, targets) if targets else None
            if target is None:
                identities.append(_new_identity(candidate))
            else:
                _merge_candidate(target, candidate)
        _validate_unique_slugs(identities)
        return identities, conflict_issues

    def _resolve_type_conflicts(
        self, candidates: list[WikiCandidate],
    ) -> tuple[list[WikiCandidate], list[WikiIssue]]:
        by_name: dict[str, list[WikiCandidate]] = {}
        for candidate in candidates:
            for name in {candidate.name, *candidate.aliases}:
                normalized = normalize_name(name)
                if normalized:
                    by_name.setdefault(normalized, []).append(candidate)

        quarantined: set[str] = set()
        issues: list[WikiIssue] = []
        reviewed_groups: set[tuple[str, ...]] = set()
        for normalized, values in sorted(by_name.items()):
            group = sorted({item.id: item for item in values}.values(), key=lambda item: item.id)
            if len({item.kind for item in group}) < 2:
                continue
            group_key = tuple(item.id for item in group)
            if group_key in reviewed_groups:
                continue
            reviewed_groups.add(group_key)
            raw = self.client.complete(
                system=(
                    "Resolve a same-name ENTITY/CONCEPT type conflict using only the supplied Evidence contexts. "
                    "Choose ENTITY only for a concrete referent, CONCEPT only for an abstract idea or method, and "
                    "UNRESOLVED when both readings remain plausible. This is classification, not identity merging."
                ),
                user={
                    "conflicting_name": normalized,
                    "candidates": [_candidate_payload(item) for item in group],
                },
                schema_name="wiki_identity_type_conflict",
                schema=_TYPE_CONFLICT_SCHEMA,
                max_tokens=900,
            )
            selected = raw.get("kind") if isinstance(raw, dict) and set(raw) == {"kind", "reason"} else "UNRESOLVED"
            reason = str(raw.get("reason", "invalid type conflict response")) if isinstance(raw, dict) else "invalid type conflict response"
            if selected not in {CandidateKind.ENTITY.value, CandidateKind.CONCEPT.value}:
                affected = group
                code = "TYPE_CONFLICT_UNRESOLVED"
            else:
                affected = [item for item in group if item.kind.value != selected]
                code = "TYPE_CONFLICT_RECLASSIFIED"
            for candidate in affected:
                quarantined.add(candidate.id)
                issues.append(WikiIssue(
                    code=code,
                    message=reason,
                    target_kind="candidate",
                    target_id=candidate.id,
                ))
        return [item for item in candidates if item.id not in quarantined], issues

    def _choose_target(
        self, candidate: WikiCandidate, targets: list[WikiIdentity],
    ) -> WikiIdentity | None:
        raw = self.client.complete(
            system=(
                "Decide whether one candidate names exactly the same entity or concept as one existing identity. "
                "Related, similar, parent-child, product-component, person-team, or topic-document relationships are not identity. "
                "Merge only when the names and supplied source context support a single real-world referent. "
                "When uncertain choose NEW. ENTITY may merge only with ENTITY and CONCEPT only with CONCEPT."
            ),
            user={
                "candidate": _candidate_payload(candidate),
                "existing_identities": [_identity_payload(item) for item in targets],
            },
            schema_name="wiki_identity_resolution",
            schema=_DECISION_SCHEMA,
            max_tokens=1000,
        )
        if not isinstance(raw, dict) or set(raw) != {"action", "target_identity_id", "reason"}:
            return None
        if raw["action"] != "MERGE":
            return None
        target_id = str(raw["target_identity_id"] or "")
        target = next((item for item in targets if item.id == target_id), None)
        if target is None or target.kind != candidate.kind:
            return None
        return target


def _exact_identity(candidate: WikiCandidate, identities: list[WikiIdentity]) -> WikiIdentity | None:
    names = {normalize_name(candidate.name), *(normalize_name(value) for value in candidate.aliases)}
    for identity in identities:
        if identity.kind != candidate.kind:
            continue
        identity_names = {
            normalize_name(identity.canonical_name),
            *(normalize_name(value) for value in identity.aliases),
        }
        if names & identity_names:
            return identity
    return None


def _lexical_targets(
    candidate: WikiCandidate,
    identities: list[WikiIdentity],
    limit: int,
) -> list[WikiIdentity]:
    candidate_names = {
        normalize_name(value) for value in [candidate.name, *candidate.aliases] if normalize_name(value)
    }
    scored: list[tuple[float, str, WikiIdentity]] = []
    for identity in identities:
        if identity.kind != candidate.kind:
            continue
        identity_names = {
            normalize_name(value)
            for value in [identity.canonical_name, *identity.aliases]
            if normalize_name(value)
        }
        score = max(
            (_lexical_score(left, right) for left in candidate_names for right in identity_names),
            default=0.0,
        )
        if score > 0:
            scored.append((score, identity.id, identity))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:limit]]


def _lexical_score(left: str, right: str) -> float:
    if left == right:
        return 1.0
    left_tokens, right_tokens = set(left.split()), set(right.split())
    left_compact = left.replace(" ", "")
    right_compact = right.replace(" ", "")
    left_initials = "".join(token[0] for token in left.split() if token)
    right_initials = "".join(token[0] for token in right.split() if token)
    acronym = 0.9 if (
        left_compact == right_initials or right_compact == left_initials
    ) and min(len(left_compact), len(right_compact)) >= 2 else 0.0
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    substring = min(len(left), len(right)) / max(len(left), len(right)) if left in right or right in left else 0.0
    sequence = SequenceMatcher(None, left, right).ratio()
    return max(acronym, overlap, substring, sequence if sequence >= 0.55 else 0.0)


def _retain_existing(
    identities: list[WikiIdentity],
    candidates: list[WikiCandidate],
    quarantined_ids: set[str],
) -> list[WikiIdentity]:
    candidate_by_id = {item.id: item for item in candidates}
    retained: list[WikiIdentity] = []
    for identity in identities:
        if not set(identity.candidate_ids) & quarantined_ids:
            retained.append(identity)
            continue
        represented = [candidate_by_id[item] for item in identity.candidate_ids if item in candidate_by_id]
        if not represented:
            continue
        identity.candidate_ids = sorted(item.id for item in represented)
        identity.source_ids = sorted({
            source_id for candidate in represented for source_id in _candidate_source_ids(candidate)
        })
        retained.append(identity)
    return retained


def _new_identity(candidate: WikiCandidate) -> WikiIdentity:
    identity_id = stable_id(
        "wi",
        candidate.scope.source_scope,
        candidate.scope.owner_id,
        candidate.scope.knowledge_base_id,
        candidate.kind.value,
        candidate.id,
    )
    return WikiIdentity(
        id=identity_id,
        scope=candidate.scope,
        kind=candidate.kind,
        canonical_name=candidate.name,
        slug=stable_slug(candidate.name, identity_id),
        category=candidate.category,
        aliases=sorted(set(candidate.aliases)),
        candidate_ids=[candidate.id],
        source_ids=_candidate_source_ids(candidate),
        description=candidate.description,
    )


def _merge_candidate(identity: WikiIdentity, candidate: WikiCandidate) -> None:
    if identity.kind != candidate.kind:
        raise ValueError("Wiki identity merge cannot cross candidate kinds")
    identity.aliases = sorted({
        *identity.aliases,
        candidate.name,
        *candidate.aliases,
    } - {identity.canonical_name})
    identity.candidate_ids = sorted({*identity.candidate_ids, candidate.id})
    identity.source_ids = sorted({*identity.source_ids, *_candidate_source_ids(candidate)})
    if not identity.description and candidate.description:
        identity.description = candidate.description


def _candidate_source_ids(candidate: WikiCandidate) -> list[str]:
    return [source_reference_id(source) for source in candidate.sources]


def _candidate_payload(candidate: WikiCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "kind": candidate.kind.value,
        "name": candidate.name,
        "category": candidate.category.value if candidate.category else None,
        "aliases": candidate.aliases,
        "description": candidate.description,
        "contexts": [source.support_quote for source in candidate.sources[:4]],
    }


def _identity_payload(identity: WikiIdentity) -> dict[str, Any]:
    return {
        "identity_id": identity.id,
        "kind": identity.kind.value,
        "canonical_name": identity.canonical_name,
        "category": identity.category.value if identity.category else None,
        "aliases": identity.aliases,
        "description": identity.description,
    }


def _validate_unique_slugs(identities: list[WikiIdentity]) -> None:
    slugs = [item.slug for item in identities]
    if len(slugs) != len(set(slugs)):
        raise ValueError("Wiki identity slugs must be unique")
    if any(item.kind not in {CandidateKind.ENTITY, CandidateKind.CONCEPT} for item in identities):
        raise ValueError("unsupported Wiki identity kind")
