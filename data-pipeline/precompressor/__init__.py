"""数据预压缩模块

提供两种压缩后端:
- EntropyCompressor: 基于 CausalLM 自信息（轻量，推荐默认）
- LLMLingua2Compressor: 基于 BERT token 分类（更精确，更重）

工厂函数:
- create_compressor(): 根据配置创建压缩器实例
"""

from precompressor.base import BasePreCompressor
from precompressor.compressor_factory import (
    CompressorMethod,
    create_compressor,
)
from precompressor.entropy_compress import EntropyCompressor
from precompressor.llmlingua2 import LLMLingua2Compressor

__all__ = [
    "BasePreCompressor",
    "EntropyCompressor",
    "LLMLingua2Compressor",
    "CompressorMethod",
    "create_compressor",
]
