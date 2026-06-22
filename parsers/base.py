from abc import ABC, abstractmethod
from models.document import Document


class BaseParser(ABC):
    """文档解析器抽象基类，所有解析器需实现 parse() 和 supported_extensions()"""

    @abstractmethod
    def parse(self, file_path: str) -> Document:
        """解析文件，返回包含全文和元数据的 Document 对象"""
        ...

    @staticmethod
    @abstractmethod
    def supported_extensions() -> list[str]:
        """返回该解析器支持的文件扩展名列表（含点号，如 ['.pdf']）"""
        ...
