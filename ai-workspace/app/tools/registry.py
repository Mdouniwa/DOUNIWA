"""ツールレジストリ。

ツール名 -> ToolAdapter インスタンスの解決を一元化する。
orchestrator はこのレジストリ経由でのみツールに触れる。
"""

from __future__ import annotations

from app.tools.base import ToolAdapter


class ToolRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ToolAdapter] = {}

    def register(self, adapter: ToolAdapter) -> None:
        if adapter.name in self._adapters:
            raise ValueError(f"tool '{adapter.name}' は既に登録されています")
        self._adapters[adapter.name] = adapter

    def get(self, name: str) -> ToolAdapter:
        if name not in self._adapters:
            known = ", ".join(sorted(self._adapters))
            raise KeyError(f"unknown tool '{name}'. registered: {known}")
        return self._adapters[name]

    def names(self) -> list[str]:
        return sorted(self._adapters)


def build_default_registry() -> ToolRegistry:
    """標準構成のレジストリを組み立てる。

    新しいツールはここに register を1行足すだけで組み込まれる。
    import を関数内に置いているのは、未使用ツールの依存を
    起動時に強制しないため。
    """
    from app.tools.browser.adapter import BrowserAdapter
    from app.tools.github.adapter import GitHubAdapter
    from app.tools.n8n.adapter import N8nAdapter
    from app.tools.nachtcode.adapter import NachtCodeAdapter
    from app.tools.obsidian.adapter import ObsidianAdapter

    registry = ToolRegistry()
    registry.register(GitHubAdapter())
    registry.register(ObsidianAdapter())
    registry.register(N8nAdapter())
    registry.register(BrowserAdapter())
    registry.register(NachtCodeAdapter())
    return registry
