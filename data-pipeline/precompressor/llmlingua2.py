"""LLMLingua-2 预压缩实现（可选升级后端）

LLMLingua-2 使用 BERT 做二元 token 分类（retain/drop），比 entropy_compress 更精确，
但需要额外的模型加载和推理开销。

对应 LightMem 的 llmlingua-2 后端。

依赖: pip install llmlingua
"""

import logging
from models.document import ContentBlock
from precompressor.base import BasePreCompressor

logger = logging.getLogger(__name__)

DEFAULT_LLMLINGUA2_MODEL = (
    "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank"
)


class LLMLingua2Compressor(BasePreCompressor):
    """LLMLingua-2 二元 token 分类压缩器

    比 entropy_compress 更精确，更适合多语言（含中文）文本。
    但需要更多 GPU 内存和更长的首次加载时间。
    """

    def __init__(
        self,
        model_name: str = DEFAULT_LLMLINGUA2_MODEL,
        device: str = "cpu",
    ):
        self.model_name = model_name
        self.device = device
        self._model = None

    @property
    def name(self) -> str:
        return "llmlingua2"

    def _load_model(self):
        """延迟加载 LLMLingua-2 模型"""
        if self._model is not None:
            return

        logger.info(f"Loading LLMLingua-2 model: {self.model_name}")
        try:
            from llmlingua import PromptCompressor

            self._model = PromptCompressor(
                model_name=self.model_name,
                device_map=self.device,
                use_auth_token=False,
            )
        except ImportError:
            raise ImportError(
                "llmlingua not installed. Run: pip install llmlingua"
            )

        logger.info(f"LLMLingua-2 model loaded: {self.model_name}")

    def compress(self, text: str, compress_rate: float = 0.6) -> str:
        """使用 LLMLingua-2 的 token 分类器压缩文本

        LLMLingua-2 为每个 token 输出 retain probability，
        保留概率高于阈值的 token。
        """
        if not text or not text.strip():
            return text

        self._load_model()

        # LLMLingua-2 的压缩 API
        # rate: 1 - compress_rate (LLMLingua 参数语义与我们的相反)
        target_token = max(1, len(text) - int(len(text) * compress_rate))

        try:
            compressed = self._model.compress_prompt(
                context=[text],
                rate=compress_rate,  # LLMLingua-2 的 rate 是保留比例
                force_tokens=["!", "?", "\n", ".", "。", "？", "！"],
            )
            if isinstance(compressed, dict):
                return compressed.get("compressed_prompt", text)
            return compressed
        except Exception as e:
            logger.warning(f"LLMLingua-2 compression failed: {e}, returning original")
            return text

    def compress_blocks(
        self, blocks: list[ContentBlock], compress_rate: float = 0.6
    ) -> list[ContentBlock]:
        """对 ContentBlock 列表做压缩"""
        result = []
        for block in blocks:
            if block.block_type in ("heading", "table"):
                result.append(block)
            elif block.text:
                compressed_text = self.compress(block.text, compress_rate)
                if compressed_text.strip():
                    new_block = ContentBlock(
                        block_type=block.block_type,
                        level=block.level,
                        text=compressed_text,
                        bold=block.bold,
                        italic=block.italic,
                    )
                    result.append(new_block)
            else:
                result.append(block)
        return result
