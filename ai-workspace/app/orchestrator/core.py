"""オーケストレータ本体。

end-to-end の一本線:
  自然言語入力 -> タスク分類 -> モデル選択 -> ツール呼び出し(stub可)
  -> LLMで結果整形 -> memory へ保存

各ステップは差し替え可能な部品（classifier / router / registry / client / store）
に委譲し、この層は制御フローだけを持つ。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.llm.client import ChatMessage, LLMClient
from app.llm.router import ModelRouter
from app.memory.store import MemoryStore, TaskRecord
from app.orchestrator.classifier import classify_task
from app.tools.base import ToolRequest, ToolResult
from app.tools.registry import ToolRegistry, build_default_registry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "あなたは個人用AIワークスペースのアシスタントです。"
    "ユーザーのタスクと、ツール実行結果（あれば）を踏まえて、"
    "簡潔かつ実用的な日本語で応答してください。"
)


@dataclass(frozen=True)
class TaskOutcome:
    """CLI へ返す実行結果のまとめ。"""

    task_text: str
    task_kind: str
    model_name: str
    route_reason: str
    tool_name: str | None
    tool_output: str | None
    llm_output: str
    stubbed: bool
    record_id: str


class Orchestrator:
    def __init__(
        self,
        router: ModelRouter | None = None,
        client: LLMClient | None = None,
        registry: ToolRegistry | None = None,
        store: MemoryStore | None = None,
    ) -> None:
        self._router = router or ModelRouter()
        self._client = client or LLMClient()
        self._registry = registry or build_default_registry()
        self._store = store or MemoryStore()

    def run(
        self,
        task_text: str,
        explicit_model: str | None = None,
        quality_first: bool = False,
        tool_params: dict | None = None,
    ) -> TaskOutcome:
        # 1. タスク分類
        classification = classify_task(task_text)
        logger.info(
            "分類: %s (tool=%s)", classification.kind.value, classification.tool_name
        )

        # 2. モデル選択
        decision = self._router.route(
            classification.kind,
            explicit_model=explicit_model,
            quality_first=quality_first,
        )

        # 3. ツール呼び出し（必要な場合のみ）
        tool_result: ToolResult | None = None
        if classification.tool_name and classification.tool_action:
            tool_result = self._run_tool(
                classification.tool_name,
                classification.tool_action,
                task_text,
                tool_params or {},
            )

        # 4. LLMで最終応答を生成
        messages = [ChatMessage("system", _SYSTEM_PROMPT)]
        if tool_result is not None:
            messages.append(ChatMessage(
                "user",
                f"タスク: {task_text}\n\n"
                f"ツール {classification.tool_name} の実行結果:\n{tool_result.output}",
            ))
        else:
            messages.append(ChatMessage("user", task_text))
        chat = self._client.chat(decision.model, messages)

        # 5. 実行ログ保存
        record = TaskRecord(
            task_text=task_text,
            task_kind=classification.kind.value,
            model_name=decision.model.name,
            route_reason=decision.reason,
            tool_name=classification.tool_name,
            tool_action=classification.tool_action,
            tool_output=tool_result.output if tool_result else "",
            llm_output=chat.content,
            stubbed=chat.stubbed or bool(tool_result and tool_result.stubbed),
        )
        self._store.save(record)

        return TaskOutcome(
            task_text=task_text,
            task_kind=classification.kind.value,
            model_name=decision.model.name,
            route_reason=decision.reason,
            tool_name=classification.tool_name,
            tool_output=tool_result.output if tool_result else None,
            llm_output=chat.content,
            stubbed=record.stubbed,
            record_id=record.id,
        )

    def _run_tool(
        self, tool_name: str, action: str, task_text: str, params: dict
    ) -> ToolResult:
        adapter = self._registry.get(tool_name)
        request = ToolRequest(action=action, params=params, task_text=task_text)
        error = adapter.validate(request)
        if error:
            return ToolResult(ok=False, output=error)
        try:
            return adapter.execute(request)
        except Exception as exc:  # ツール実装のバグで全体を落とさない
            logger.exception("tool '%s' の実行中に予期しないエラー", tool_name)
            return ToolResult(ok=False, output=f"tool '{tool_name}' 実行エラー: {exc}")
