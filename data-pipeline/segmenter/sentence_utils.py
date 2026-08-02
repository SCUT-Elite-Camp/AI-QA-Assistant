"""Chinese/English mixed sentence splitting utilities

Used by SimilaritySegmenter for B2 semantic boundary detection.
"""

import re
from typing import List


# Chinese sentence-ending punctuation (split AFTER these)
_CN_SENTENCE_ENDS = re.compile(r"(?<=[.!?;!?;])")

# Double newlines = stronger paragraph boundary
_NEWLINE_SEP = re.compile(r"\n{2,}")

# English sentence end pattern (period/exclamation/question + space + capital)
_EN_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def split_sentences(text: str) -> list[str]:
    """Split text into sentences (Chinese + English mixed)

    Strategy:
    1. Split by double newlines first (paragraph boundary)
    2. Within each paragraph, split on sentence-ending punctuation
    3. English: split on .!? followed by space + capital letter

    Args:
        text: Input text (Chinese and/or English)

    Returns:
        List of non-empty sentences
    """
    # Step 1: Split by double newlines
    paragraphs = _NEWLINE_SEP.split(text)

    sentences = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Step 2: Split on sentence-ending punctuation
        # First handle Chinese punctuation by inserting newlines
        para = para.replace("。", "。\n")   # 。
        para = para.replace("！", "！\n")   # ！
        para = para.replace("？", "？\n")   # ？
        para = para.replace("；", "；\n")   # ；
        para = para.replace("\n{3,}", "\n\n")

        lines = para.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Step 3: English sentence splitting
            en_sentences = _EN_SENTENCE_END.split(line)
            for s in en_sentences:
                s = s.strip()
                if s and len(s) >= 2:  # Minimum 2 chars to be a sentence
                    sentences.append(s)

    return sentences


def split_sentences_simple(text: str) -> list[str]:
    """Simplified sentence splitting (Chinese-focused, speed priority)

    Replaces Chinese punctuation with punctuation + newline, then splits.
    """
    # Replace Chinese punctuation marks with themselves + newline
    for punct in ["。", "！", "？", "；"]:  # 。！？；
        text = text.replace(punct, punct + "\n")

    text = re.sub(r"\n{3,}", "\n\n", text)

    lines = text.split("\n")
    return [line.strip() for line in lines if line.strip() and len(line.strip()) >= 2]


def merge_short_sentences(
    sentences: list[str],
    min_chars: int = 20,
) -> list[str]:
    """Merge very short sentences into adjacent ones

    Prevents ultra-short sentences (like "Yes.") from becoming isolated
    semantic units.

    Args:
        sentences: Sentence list
        min_chars: Minimum sentence length (shorter ones get merged)

    Returns:
        Merged sentence list
    """
    if not sentences:
        return sentences

    merged = []
    buffer = ""

    for s in sentences:
        if len(s) < min_chars:
            buffer += s
        else:
            if buffer:
                merged.append(buffer + s)
                buffer = ""
            else:
                merged.append(s)

    # Handle trailing buffer
    if buffer:
        if merged:
            merged[-1] += buffer
        else:
            merged.append(buffer)

    return merged


def count_chinese_chars(text: str) -> int:
    """Count Chinese characters in text"""
    cnt = 0
    for ch in text:
        if "一" <= ch <= "鿿":
            cnt += 1
    return cnt


def is_mostly_chinese(text: str, threshold: float = 0.3) -> bool:
    """Check if text is predominantly Chinese"""
    total = len(text.replace(" ", "").replace("\n", ""))
    if total == 0:
        return False
    cn = count_chinese_chars(text)
    return cn / total >= threshold
