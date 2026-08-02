"""预压缩器工厂

用法:
    compressor = create_compressor("entropy_compress", model_name="gpt2")
    compressed_text = compressor.compress(text, compress_rate=0.6)
"""

import logging
from typing import Literal

from precompressor.base import BasePreCompressor

logger = logging.getLogger(__name__)

CompressorMethod = Literal["entropy_compress", "llmlingua2", "none"]


def create_compressor(
    method: CompressorMethod = "entropy_compress", **kwargs
) -> BasePreCompressor | None:
    """根据配置创建压缩器实例

    Args:
        method: 压缩方法
            - "entropy_compress": CausalLM 自信息过滤（推荐默认）
            - "llmlingua2": BERT token 分类器
            - "none": 不压缩，返回 None
        **kwargs: 传递给具体压缩器的参数

    Returns:
        BasePreCompressor 实例，或 None（method="none" 时）
    """
    if method == "none":
        return None

    if method == "entropy_compress":
        from precompressor.entropy_compress import EntropyCompressor

        return EntropyCompressor(
            model_name=kwargs.get("model_name", "gpt2"),
            device=kwargs.get("device", "cpu"),
            word_strategy=kwargs.get("word_strategy", "average"),
            max_length=kwargs.get("max_length", 1024),
        )

    if method == "llmlingua2":
        from precompressor.llmlingua2 import LLMLingua2Compressor

        return LLMLingua2Compressor(
            model_name=kwargs.get(
                "model_name",
                "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
            ),
            device=kwargs.get("device", "cpu"),
        )

    raise ValueError(f"Unknown compressor method: {method}")
