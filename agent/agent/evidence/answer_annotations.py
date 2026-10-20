"""Project accepted bindings onto the final answer without exposing verification internals."""

import re

from agent.schemas.chat import AnswerClaimAnnotation, AnswerClaimQuote


def _projection(text):
    """Ignore citation renumbering and layout normalization, retaining source offsets."""
    chars, positions = [], []
    cursor = 0
    for marker in [*re.finditer(r"\[\d+\]", text), None]:
        end = marker.start() if marker else len(text)
        for index in range(cursor, end):
            char = text[index]
            if char.isspace():
                if chars and chars[-1] != " ":
                    chars.append(" ")
                    positions.append(index)
            else:
                chars.append(char)
                positions.append(index)
        cursor = marker.end() if marker else len(text)
    if chars and chars[-1] == " ":
        chars.pop()
        positions.pop()
    return "".join(chars), positions


def answer_annotations(binding, answer, citations):
    if not binding or not binding.get("valid") or not answer:
        return []
    original, original_positions = _projection(binding.get("model_answer", ""))
    final, final_positions = _projection(answer)
    if original != final:
        return []  # Never attach an old binding to a changed/repaired body.
    annotations = []
    for claim in binding.get("claims", []):
        supports = []
        for fragment in claim["supports"]:
            matched = [citation for citation in citations if all(
                getattr(citation, key, None) == fragment.get(key)
                for key in ("doc_id", "chunk_id", "evidence_ref", "content_hash", "source_version")
            )]
            if len(matched) != 1:
                return []
            supports.append(AnswerClaimQuote(citation_id=matched[0].citation_id, quote=fragment.get("quote")))
        for span in claim["model_answer_spans"]:
            indices = [index for index, offset in enumerate(original_positions)
                       if span["start"] <= offset < span["end"]]
            if not indices:
                return []
            start, end = final_positions[indices[0]], final_positions[indices[-1]] + 1
            annotations.append(AnswerClaimAnnotation(claim_id=claim["claim_id"], text=answer[start:end],
                                                     start=start, end=end, supports=supports))
    return sorted(annotations, key=lambda item: item.start)
