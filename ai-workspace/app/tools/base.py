"""ツールアダプタの共通インターフェース。

すべてのツール（GitHub / Obsidian / n8n / browser / 将来の追加分）は
ToolAdapter を継承し、execute() を実装する。

orchestrator はこのインターフェースにのみ依存し、
個別ツールの実装詳細を知らない。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolRequest:
    """orchestrator からツールへ渡す実行要求。

    action はツールごとに定義される操作名（例: github の "read_readme"）。
    params は action ごとの引数。task_text は元の自然言語指示で、
    LLMに文脈を渡したいツールが参照できるよう常に含める。
    """

    action: str
    params: dict = field(default_factory=dict)
    task_text: str = ""


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str
    stubbed: bool = False   # True なら実接続せず stub 動作
    data: dict = field(default_factory=dict)


class ToolAdapter(ABC):
    """全ツール共通の基底クラス。"""

    #: レジストリ登録・ログ・ルーティングに使う一意な名前
    name: str = "base"

    #: このツールがサポートする action 一覧（ドキュメント兼バリデーション用）
    supported_actions: tuple[str, ...] = ()

    #: action -> 説明（params の書き方を含む）。planner のツールカタログ生成に使う
    action_docs: dict[str, str] = {}

    #: 副作用（保存・送信等）を伴う action。実行計画の安全ガードが回数を制限する
    write_actions: tuple[str, ...] = ()

    @abstractmethod
    def execute(self, request: ToolRequest) -> ToolResult:
        """要求を実行する。失敗時は例外ではなく ok=False で返す。"""

    def validate(self, request: ToolRequest) -> str | None:
        """実行前チェック。問題があればエラーメッセージ、なければ None。"""
        if self.supported_actions and request.action not in self.supported_actions:
            return (
                f"tool '{self.name}' は action '{request.action}' を"
                f" サポートしません。対応: {', '.join(self.supported_actions)}"
            )
        return None
