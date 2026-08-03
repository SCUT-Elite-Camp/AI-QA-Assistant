"""
Token 计数工具。

提供快速估算文本 token 数的函数，不依赖昂贵的分词器。
中文：字符数 / 1.5 ≈ token 数
英文：字符数 / 4 ≈ token 数
混合：取两者平均
"""

import re


# CJK 字符正则（覆盖常用 Unicode 区块）
# CJK Radicals Supplement, Kangxi Radicals, CJK Symbols, CJK Unified Ideographs,
# CJK Compatibility Ideographs, CJK Compatibility Forms, CJK Extension A
_CJK_RE = re.compile(
    r"[⺀-⿟　-〿㐀-䶿"
    r"一-鿿豈-﫿︰-﹏"
    r"\U00020000-\U0002A6DF\U0002F800-\U0002FA1F]"
)


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数量（适用于中英文混合）。

    采用启发式方法：中文字符约占 1.5 字符/token，英文约占 4 字符/token。

    Args:
        text: 待估算的文本

    Returns:
        估算的 token 数（整数，至少为 1）
    """
    if not text:
        return 0

    cjk_chars = len(_CJK_RE.findall(text))
    non_cjk_chars = len(text) - cjk_chars

    # 中文约 1.5 字符/token，英文约 4 字符/token
    estimated = (cjk_chars / 1.5) + (non_cjk_chars / 4.0)
    return max(1, int(estimated))


def estimate_tokens_batch(texts: list[str]) -> list[int]:
    """批量估算 token 数"""
    return [estimate_tokens(t) for t in texts]


def truncate_by_tokens(text: str, max_tokens: int) -> str:
    """按 token 预算截断文本。

    从文本开头保留最多 max_tokens 个 token（估算值）。

    Args:
        text: 原始文本
        max_tokens: 最大 token 数

    Returns:
        截断后的文本，若原文本不超限则返回原文本
    """
    if not text or max_tokens <= 0:
        return ""

    total = estimate_tokens(text)
    if total <= max_tokens:
        return text

    # 按比例截断字符
    ratio = max_tokens / total
    # 留 5% 余量
    target_chars = int(len(text) * ratio * 0.95)

    # 尝试在句子边界截断
    cut_point = target_chars
    for sep in ("\n\n", "\n", "。", "；", "，", ".", ";", ",", " "):
        pos = text.rfind(sep, 0, target_chars)
        if pos > target_chars * 0.7:  # 不要太早截断
            cut_point = pos + len(sep)
            break

    return text[:cut_point].strip()
