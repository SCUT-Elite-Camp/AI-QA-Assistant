"""Explicit same-generation protocol adapter for scripted test models.

Bindings here are test data, never an entailment judgment. Production models
must produce this envelope themselves. Raw JSON is deliberately left untouched
so malformed response tests exercise the real rejection path.
"""

import json
import re
from functools import wraps

from agent.evidence.citation import normalize_citation_markers
from agent.evidence.answer_grounding import GROUNDING_INSTRUCTION


def grounded_content(answer, messages):
    texts = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.extend(item.get("text", "") for item in content if item.get("type") == "text")
    if not any(GROUNDING_INSTRUCTION.splitlines()[0] in text for text in texts):
        return answer
    if not isinstance(answer, str) or not answer.strip() or answer.lstrip().startswith(("{", "[")):
        # A citation-leading answer is still plain text.
        if not isinstance(answer, str) or not re.match(r"\[\d+\]", answer.lstrip()):
            return answer
    answer = re.sub(r"^\[TITLE:[^\n]*\]\s*", "", answer).strip()
    answer = normalize_citation_markers(answer)
    sources = {}
    images = set()
    for text in texts:
        if text.startswith('Authorized reference context ('):
            references, _ = json.JSONDecoder().raw_decode(text.split('\n', 1)[1])
            sources.update({item['citation_id']: item['content'].strip().splitlines()[0]
                            for item in references if item['content'].strip()})
        for match in re.finditer(r"(?m)^\[(\d+)\] [Tt]itle: [^\n]*\n(?:doc_id: [^\n]*\nchunk_id: [^\n]*\n)?[Cc]ontent: ([^\n]+)", text):
            sources[int(match[1])] = match[2].strip()
        # Completeness repair supplies a compact, one-line evidence format.
        if "Evidence:\n" in text:
            for match in re.finditer(r"(?m)^\[(\d+)\] [^\n:]*: ([^\n]+)", text):
                sources[int(match[1])] = match[2].strip()
        images.update(int(value) for value in re.findall(r"Original image for reference \[(\d+)\]", text))
    supports = []
    for ref in sorted({int(value) for value in re.findall(r"\[(\d+)\]", answer)}):
        fragment = {"image_region": [0.0, 0.0, 1.0, 1.0]} if ref in images else {"quote": sources.get(ref, "missing test source")}
        supports.append({"citation_id": ref, **fragment})
    return json.dumps({"claims": [{"text": answer, "supports": supports}]}, ensure_ascii=False)


def grounded_model(chat):
    @wraps(chat)
    def wrapped(self, messages, *args, **kwargs):
        # Scripted providers emulate the envelope rather than an HTTP backend.
        if "response_format" in kwargs:
            assert kwargs.pop("response_format") == {"type": "json_object"}
        response = chat(self, messages, *args, **kwargs)
        if isinstance(response, dict) and not response.get("tool_calls"):
            return {**response, "content": grounded_content(response.get("content"), messages)}
        return response
    return wrapped
