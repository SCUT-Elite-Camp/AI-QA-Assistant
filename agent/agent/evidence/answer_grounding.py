"""Private claim/source binding. Semantic support is deliberately not judged here."""

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


GROUNDING_INSTRUCTION = '''[ANSWER_GROUNDING_V3]
When answering from numbered source evidence, return exactly one JSON object, no
Markdown fence, preamble, TITLE metadata or text outside JSON:
{"claims":[
{"text":"Alpha is complete.","supports":[{"citation_id":1,"quote":"Alpha: complete"}]},
{"text":"Beta has three steps.","supports":[{"citation_id":2,"quote":"Beta: 3 steps"}]}]}
Each claim.text is a user-visible paragraph. The server joins these paragraphs
in order to form the complete answer; supports remains private validation data.
Return only the object with its claims list, never a separate answer field. Avoid headings or
unbound introductions. Express all answer content in these grounded paragraphs.
Write short sentences, each expressing one independently checkable fact with an
explicit subject. Different owners, dates, counts or statuses are separate claims,
even if they come from the same row. Do not wrap a multi-fact answer as one claim.
Each support must reference the numbered evidence for that claim and provide a
short verbatim quote. Do not output confidence, scores or verification verdicts.
Reference numbers identify individual excerpts, NOT documents or titles. Copy
the citation_id of the exact excerpt containing your quote. A title-only or
introductory excerpt cannot support text found in a different excerpt of the
same document. Never reuse reference numbers from conversation history. Check
each quote against the Content of its selected current reference before output.
Never infer an unrecorded year,
number, owner or status. Preserve the source's precision, including month/day-only dates.
The server renders [n] citations from supports; do not duplicate them in answer.
Do not invent a quote or reference. To abstain, return {"claims":[]}.
For an original-image reference (content_kind=file), use quote=null and
image_region=[left,top,right,bottom] in normalized coordinates [0,1] instead of
inventing textual evidence. Textual references require quote and no image_region.
Tool calls may still be used when tools are offered; a final evidence-based
answer must obey this JSON contract. Never put claim metadata in reasoning output.
[/ANSWER_GROUNDING_V3]'''


class ClaimSupport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    citation_id: int = Field(ge=1)
    quote: str | None = Field(default=None, min_length=1, max_length=6000)
    image_region: list[float] | None = Field(default=None, min_length=4, max_length=4)

    @model_validator(mode="after")
    def one_source_fragment(self):
        if (self.quote is None) == (self.image_region is None):
            raise ValueError("one source fragment required")
        if self.quote is not None and not self.quote.strip():
            raise ValueError("empty quote")
        if self.image_region is not None:
            left, top, right, bottom = self.image_region
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                raise ValueError("invalid image region")
        return self


class AnswerClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str = Field(min_length=1, max_length=20000)
    supports: list[ClaimSupport] = Field(min_length=1, max_length=20)


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    claims: list[AnswerClaim] = Field(max_length=100)

    @property
    def answer(self) -> str:
        return "\n\n".join(claim.text for claim in self.claims)

    @model_validator(mode="after")
    def bounded_answer(self):
        if len(self.answer) > 40000:
            raise ValueError("answer too long")
        return self


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def parse_grounded_answer(content: str) -> GroundedAnswer:
    if not isinstance(content, str) or len(content) > 500000:
        raise ValueError("invalid_grounding_format")
    try:
        payload = json.loads(content, object_pairs_hook=_unique_object)
        return GroundedAnswer.model_validate(payload)
    except (ValueError, TypeError, ValidationError) as exc:
        raise ValueError("invalid_grounding_format") from exc


def _normalized_positions(value):
    chars, positions = [], []
    for index, char in enumerate(value):
        if char.isspace():
            if chars and chars[-1] != " ":
                chars.append(" ")
                positions.append(index)
        else:
            chars.append(char)
            positions.append(index)
    return "".join(chars).rstrip(), positions


def validate_grounded_answer(draft: GroundedAnswer, evidence) -> dict[str, Any]:
    """Resolve real excerpts and complete answer bindings, without semantic grading.

    Citation numbers are derived from the binding, so forgetting to repeat them
    in the visible answer cannot invalidate an otherwise complete binding.
    """
    sources = [item if isinstance(item, dict) else item.model_dump() for item in evidence]
    errors, resolved = [], []
    paragraphs = []
    answer_offset = 0
    for index, claim in enumerate(draft.claims):
        claim_key = f"claim_{index + 1}"
        if not any(char.isalnum() for char in claim.text):
            errors.append(f"{claim_key}:empty_claim")
        fragments = []
        for support in claim.supports:
            key = f"{claim_key}:reference_{support.citation_id}"
            fragment = support.model_dump(exclude_none=True)
            if support.citation_id > len(sources):
                fragments.append(fragment)
                errors.append(f"{key}:invalid_reference")
                continue
            source = sources[support.citation_id - 1]
            fragment = {**fragment,
                        **{name: source.get(name) for name in
                           ("source_type", "source_scope", "doc_id", "chunk_id", "evidence_ref",
                            "content_hash", "source_version", "version_id", "attachment_id", "evidence_id")}}
            if source.get("content_kind", "excerpt") == "file":
                if support.image_region is None:
                    errors.append(f"{key}:image_region_required")
                fragment["image_region"] = support.image_region
            else:
                original = source.get("content", source.get("chunk_text", ""))
                normalized, positions = _normalized_positions(original)
                quote = " ".join((support.quote or "").split())
                offset = normalized.find(quote) if quote else -1
                if support.image_region is not None or offset < 0:
                    errors.append(f"{key}:quote_not_in_source")
                else:
                    start, end = positions[offset], positions[offset + len(quote) - 1] + 1
                    fragment.update(quote=original[start:end], source_start=start, source_end=end)
            fragments.append(fragment)
        refs = {support.citation_id for support in claim.supports}
        present = {int(value) for value in re.findall(r"\[(\d+)\]", claim.text)}
        if present - refs:
            errors.append(f"{claim_key}:citation_without_claim_support")
        spans = [{"start": answer_offset, "end": answer_offset + len(claim.text)}]
        answer_offset += len(claim.text) + 2
        paragraphs.append(claim.text + "".join(f"[{ref}]" for ref in sorted(refs - present)))
        resolved.append({"claim_id": claim_key, "text": claim.text,
                         "model_answer_spans": spans, "supports": fragments})
    if not draft.answer.strip() or not draft.claims:
        errors.append("missing_answer_or_claims")
    rendered = "\n\n".join(paragraphs) if not errors else ""
    return {"valid": not errors, "validation_kind": "binding", "semantic_validation": "not_performed",
            "model_answer": draft.answer, "answer": rendered, "errors": list(dict.fromkeys(errors)),
            "claims": resolved}
