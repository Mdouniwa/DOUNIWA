"""tools層: 外部連携アダプタの差し込み口。

新しいツールを追加する手順:
  1. app/tools/<name>/adapter.py に ToolAdapter を実装
  2. registry.py の build_default_registry() に登録
  3. （必要なら）orchestrator/classifier.py にタスク種別との対応を追加
"""

from app.tools.base import ToolAdapter, ToolRequest, ToolResult
from app.tools.registry import ToolRegistry, build_default_registry

__all__ = [
    "ToolAdapter",
    "ToolRequest",
    "ToolResult",
    "ToolRegistry",
    "build_default_registry",
]
