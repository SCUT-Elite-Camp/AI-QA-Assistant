"""预压缩模块基类

从 LightMem 项目借鉴：
- entropy_compress: CausalLM 自信息过滤（轻量，文本通用）
- llmlingua-2: BERT 二元 token 分类器（更精确，更重）

"""

from abc import ABC, abstractmethod
from models.document import ContentBlock


class BasePreCompressor(ABC):
    """预压缩器抽象基类"""

    @abstractmethod
    def compress(self, text: str, compress_rate: float = 0.6) -> str:
        """对纯文本做信息密度过滤，返回压缩后的文本

        Args:
            text: 输入文本
            compress_rate: 保留比例 (0~1)，默认保留 60% 高信息量内容

        Returns:
            压缩后的文本字符串
        """
        ...

    @abstractmethod
    def compress_blocks(
        self, blocks: list[ContentBlock], compress_rate: float = 0.6
    ) -> list[ContentBlock]:
        """对 ContentBlock 列表做压缩

        默认实现：合并所有块→压缩→简单回填。
        子类可覆写以保留结构化信息（如标题不压缩、表格特殊处理等）。

        Args:
            blocks: 解析器输出的内容块列表
            compress_rate: 保留比例

        Returns:
            压缩后的 ContentBlock 列表
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """压缩器名称"""
        ...
