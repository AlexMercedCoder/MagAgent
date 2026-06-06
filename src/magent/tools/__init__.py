"""Built-in tool executor public API.

The implementation lives in :mod:`magent.tools.executor` so package import
initialization stays lightweight while preserving ``from magent.tools import
ToolExecutor`` compatibility.
"""

from magent.tools.executor import ToolExecutor, asyncio, shutil

__all__ = ["ToolExecutor", "asyncio", "shutil"]
