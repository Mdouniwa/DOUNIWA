"""LLM生成ステップ用アダプタ。

「READMEを要約してObsidianに保存」のような複合タスクでは、
ツール出力の要約・変換・生成を計画の1ステップとして表現する必要がある。
これを他ツールと同じ ToolAdapter として提供し、planner が
llm.generate ステップとして計画に組み込めるようにする。

LLMClient と使用モデルが必要なため build_default_registry() には含めず、
Orchestrator が自身の client を渡して登録する。
"""

from __future__ import annotations

import logging

from app.llm.client import ChatMessage, LLMClient
from app.llm.models import DEFAULT_MODEL, ModelSpec, get_model
from app.tools.base import ToolAdapter, ToolRequest, ToolResult

logger = logging.getLogger(__name__)


class LLMGenAdapter(ToolAdapter):
    name = "llm"
    supported_actions = ("generate",)
    action_docs = {
        "generate": (
            "テキストの要約・変換・生成を行う。前ステップの出力を加工するときに使う。"
            ' params: {"prompt": "指示と対象テキストを含む文字列"}'
        ),
    }

    def __init__(self, client: LLMClient, model: ModelSpec | None = None) -> None:
        self._client = client
        self._model = model

    def execute(self, request: ToolRequest) -> ToolResult:
        prompt = request.params.get("prompt") or request.task_text
        model = self._model or get_model(DEFAULT_MODEL)
        chat = self._client.chat(model, [ChatMessage("user", prompt)])
        # stub 応答は「生成できていない」のと同じなので、そのまま stubbed で伝える
        return ToolResult(ok=True, output=chat.content, stubbed=chat.stubbed)
