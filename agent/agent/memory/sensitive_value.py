"""Pure sensitivity rules shared by persistent-memory planning work."""

from __future__ import annotations

import re


_SENSITIVE_KEYWORDS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api key",
    "private key",
    "access key",
    "银行卡",
    "银行账户",
    "账号",
    "住址",
    "详细地址",
    "诊断",
    "病历",
    "疾病",
    "药物",
    "金融账户",
)
_CHINESE_ID_PATTERN = re.compile(r"\b\d{17}[\dXx]\b")
_NON_DIGIT_PATTERN = re.compile(r"\D+")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def isSensitiveMemoryValue(text: str) -> bool:
    """Return whether a complete value must be excluded from Snapshot summaries.

    The function is intentionally deterministic and side-effect free: callers must
    omit the entire matching message and must never log the value being checked.
    """

    normalized = _WHITESPACE_PATTERN.sub(" ", text.casefold())
    if any(keyword in normalized for keyword in _SENSITIVE_KEYWORDS):
        return True
    if _CHINESE_ID_PATTERN.search(text):
        return True

    digit_count = len(_NON_DIGIT_PATTERN.sub("", text))
    return 13 <= digit_count <= 19
