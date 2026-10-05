"""Narrow ambiguity checks for claims about the latest architecture."""
import re


def needs_architecture_scope(query: str) -> bool:
    text = query.strip()
    architecture = re.search(r"\barchitecture\b", text, re.I)
    latest = re.search(r"\b(?:latest|current)\b", text, re.I)
    scope = re.search(
        r"\b(?:code|implementation|deployed|production|target|planned|design|branch|commit|release|version|as of)\b"
        r"|\b20\d{2}\b|\bW\d{2}\b|\b[a-f0-9]{7,40}\b", text, re.I,
    )
    return bool(architecture and latest and not scope)


ARCHITECTURE_SCOPE_QUESTION = (
    "Please clarify which architecture you mean: the current code implementation, "
    "the planned target architecture, or a demonstrated architecture at a particular date. "
    "Specify the branch, release or date if you want the current implementation."
)
