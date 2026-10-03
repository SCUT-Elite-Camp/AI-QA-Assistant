"""Stable public API for the data persistence layer.

Import a domain module from this package instead of depending on the internal
``storage`` or ``services`` package layout. Domain modules are loaded on first
access so optional backends, such as Milvus, stay optional.

This facade currently relies on the runtime placing ``data-persistence/`` on
``PYTHONPATH`` or ``sys.path``. Packaging and bootstrap consolidation are
deferred; consumers should depend on ``data_persistence.*`` domain modules.
"""

from importlib import import_module
from typing import Any

__all__ = ["documents", "chat", "vector", "wiki", "topics"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f".{name}", __name__)
    globals()[name] = module
    return module


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
