from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseTool(ABC):
    """Abstract base class for all Agent tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """The tool's name identifier (e.g. 'search_documents')."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """A detailed description of what the tool does and when to use it."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON schema representation of the tool parameters."""
        pass

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any:
        """Executes the tool's core logic with keyword arguments."""
        pass

    def to_openai_schema(self) -> Dict[str, Any]:
        """Converts the tool definition to OpenAI function call schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }
