"""browser / computer-use アダプタの抽象層。

今日のスコープでは実装しない。ただし interface を先に固定し、
将来 browser-use / Playwright / computer-use を差し込めるようにする。

設計方針:
  - orchestrator からは他ツールと同じ ToolAdapter として見える
  - 実装を差し替える時は BrowserBackend を実装して
    BrowserAdapter(backend=...) を registry に登録するだけでよい
  - セッション（開いているページ・ログイン状態）は backend 側が保持する
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.tools.base import ToolAdapter, ToolRequest, ToolResult


class BrowserBackend(ABC):
    """browser/computer 操作の実体を差し込むためのインターフェース。

    将来の実装候補: browser-use, Playwright, macOS computer-use。
    """

    @abstractmethod
    def open_url(self, url: str) -> str:
        """URL を開き、ページ内容のテキスト表現を返す。"""

    @abstractmethod
    def act(self, instruction: str) -> str:
        """自然言語指示でページ操作（クリック・入力等）を行い、結果を返す。"""

    @abstractmethod
    def extract(self, query: str) -> str:
        """現在のページから query に該当する情報を抽出して返す。"""


class StubBrowserBackend(BrowserBackend):
    """未実装であることを明示するだけの backend。"""

    def open_url(self, url: str) -> str:
        return f"[stub:browser] open_url('{url}') は未実装です。"

    def act(self, instruction: str) -> str:
        return f"[stub:browser] act('{instruction[:100]}') は未実装です。"

    def extract(self, query: str) -> str:
        return f"[stub:browser] extract('{query[:100]}') は未実装です。"


class BrowserAdapter(ToolAdapter):
    name = "browser"
    supported_actions = ("open_url", "act", "extract")

    def __init__(self, backend: BrowserBackend | None = None) -> None:
        self._backend = backend or StubBrowserBackend()

    def execute(self, request: ToolRequest) -> ToolResult:
        stubbed = isinstance(self._backend, StubBrowserBackend)
        if request.action == "open_url":
            output = self._backend.open_url(request.params.get("url", ""))
        elif request.action == "act":
            output = self._backend.act(request.params.get("instruction", request.task_text))
        elif request.action == "extract":
            output = self._backend.extract(request.params.get("query", request.task_text))
        else:
            return ToolResult(ok=False, output=f"unknown action: {request.action}")
        return ToolResult(ok=True, output=output, stubbed=stubbed)
