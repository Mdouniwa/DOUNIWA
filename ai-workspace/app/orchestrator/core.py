"""オーケストレータ本体。

end-to-end の一本線:
  自然言語入力 -> 実行計画の生成(planner) -> モデル選択
  -> ステップ実行(executor) -> LLMで結果整形 -> memory へ保存

各ステップは差し替え可能な部品（planner / executor / router / registry /
client / store）に委譲し、この層は制御フローだけを持つ。

信頼性の原則（2026-07-16 の虚偽成功報告バグの再発防止）:
  - 最終応答生成プロンプトには「計画」と「ステップごとの実行ステータス一覧」を
    必ず渡す。LLMは実行結果に書かれた事実しか報告してはならない。
  - 安全ガードで拒否された計画は LLM を通さず、決定的なメッセージで
    「何も実行していない」ことを報告する。
  - CLI 向けに StepResult 一覧をそのまま返し、LLMの作文と独立に
    ステップごとの成否を確認できるようにする。
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass

from app.llm.client import ChatMessage, LLMClient
from app.llm.models import get_model
from app.llm.router import ModelRouter
from app.memory.store import MemoryStore, TaskRecord
from app.orchestrator.classifier import TaskKind
from app.orchestrator.executor import StepResult, execute_plan
from app.orchestrator.planner import Plan, Planner, PlanRejected
from app.tools.registry import ToolRegistry, build_default_registry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "あなたは個人用AIワークスペースのアシスタントです。"
    "ユーザーのタスクと、実行計画の各ステップの実行結果を踏まえて、"
    "簡潔かつ実用的な日本語で応答してください。"
    "報告できるのは、実行結果に事実として書かれている内容だけです。"
    "実行されていない・スキップされた・失敗したステップを"
    "完了したと述べてはいけません。ステータスが stub のステップは"
    "実際には実行されていません。一部のステップだけが成功した場合は、"
    "どこまで完了しどこで止まったかを正直に説明してください。"
    "「直近のタスク履歴」が与えられた場合、過去の結果への質問には"
    "その内容を参照して答えてよいですが、履歴にある操作を今回"
    "実行したかのように述べてはいけません。"
)

# 直近何件のタスク記録をコンテキストとして渡すか（0で無効）
_DEFAULT_CONTEXT_RECENT_TASKS = 3
# コンテキストに載せる1レコードあたりの結果テキスト上限（文字）
_MAX_CONTEXT_OUTPUT_CHARS = 400

# タスク文がこれらを含むときだけ履歴をプロンプトに渡す。
# 履歴を無条件に渡すと、reasoning モデル（Qwen3.6）が余計な文脈で
# 思考を発散させ content が返らないことがあるため（2026-07-16 実測）。
_HISTORY_HINTS = ("さっき", "さきほど", "先ほど", "前回", "直前", "この前", "履歴")

# 最終プロンプトに載せる1ステップあたりの出力上限（文字）
_MAX_STEP_OUTPUT_CHARS = 3000

# 計画の先頭ツール -> ルーティング用タスク種別（llm は変換ステップなので除外）
_TOOL_TO_KIND = {
    "github": TaskKind.CODE,
    "obsidian": TaskKind.WRITE_NOTE,
    "n8n": TaskKind.AUTOMATION,
    "browser": TaskKind.BROWSER,
}


@dataclass(frozen=True)
class TaskOutcome:
    """CLI へ返す実行結果のまとめ。"""

    task_text: str
    task_kind: str
    model_name: str
    route_reason: str
    plan_source: str           # "llm" | "rules" | "fast"
    plan_note: str             # フォールバック理由・拒否理由等
    plan_rejected: bool        # 安全ガードで拒否され、何も実行していない
    steps: tuple[StepResult, ...]
    tool_name: str | None      # 互換: 最初のステップのツール名
    tool_ok: bool | None       # 互換: 全ステップが成功したか（ステップなしは None）
    tool_output: str | None    # 互換: 最後に実行されたステップの出力
    llm_output: str
    stubbed: bool
    record_id: str


def _context_recent_tasks() -> int:
    try:
        return int(os.environ.get(
            "CONTEXT_RECENT_TASKS", _DEFAULT_CONTEXT_RECENT_TASKS
        ))
    except ValueError:
        return _DEFAULT_CONTEXT_RECENT_TASKS


def _needs_history(task_text: str) -> bool:
    return any(hint in task_text for hint in _HISTORY_HINTS)


def _build_recent_context(records: list[dict]) -> str:
    """直近のタスク記録を、プロンプトに載せる参考情報テキストへ変換する。"""
    if not records:
        return ""
    lines = ["直近のタスク履歴（古い順・参考情報。今回実行した操作ではない）:"]
    for r in records:
        task = str(r.get("task_text") or "")[:100]
        output = str(r.get("llm_output") or r.get("tool_output") or "").strip()
        lines.append(f"- タスク: {task}")
        lines.append(f"  結果: {output[:_MAX_CONTEXT_OUTPUT_CHARS]}")
    return "\n".join(lines)


def _previous_output(records: list[dict]) -> str | None:
    """{{previous.output}} の解決に使う、直前タスクの結果テキスト。"""
    if not records:
        return None
    last = records[-1]
    output = str(last.get("llm_output") or last.get("tool_output") or "").strip()
    return output or None


def _kind_for_plan(plan: Plan) -> TaskKind:
    for step in plan.steps:
        kind = _TOOL_TO_KIND.get(step.tool)
        if kind is not None:
            return kind
    return TaskKind.GENERAL


def _build_step_report(plan: Plan, results: list[StepResult]) -> str:
    lines = [f"実行計画（生成方式: {plan.source}）:"]
    for i, step in enumerate(plan.steps, start=1):
        lines.append(f"  {i}. {step.label}")
    lines.append("")
    lines.append("各ステップの実行結果:")
    for r in results:
        lines.append(f"[step {r.index}] {r.label} -> {r.status}")
        if not r.skipped:
            output = r.output[:_MAX_STEP_OUTPUT_CHARS]
            if len(r.output) > _MAX_STEP_OUTPUT_CHARS:
                output += "…（以降省略）"
            lines.append(f"出力:\n{output}")
    return "\n".join(lines)


class Orchestrator:
    def __init__(
        self,
        router: ModelRouter | None = None,
        client: LLMClient | None = None,
        registry: ToolRegistry | None = None,
        store: MemoryStore | None = None,
        planner: Planner | None = None,
    ) -> None:
        self._router = router or ModelRouter()
        self._client = client or LLMClient()
        self._registry = registry or build_default_registry()
        self._ensure_llm_tool()
        self._store = store or MemoryStore()
        self._planner = planner or Planner(self._client, self._registry)

    def _ensure_llm_tool(self) -> None:
        """要約・変換ステップ用の llm.generate をレジストリに揃える。"""
        try:
            self._registry.get("llm")
        except KeyError:
            from app.tools.llm_gen.adapter import LLMGenAdapter
            self._registry.register(LLMGenAdapter(self._client))

    def run(
        self,
        task_text: str,
        explicit_model: str | None = None,
        quality_first: bool = False,
        tool_params: dict | None = None,
    ) -> TaskOutcome:
        # 明示指定モデルは計画生成にも使う（不正名はここで KeyError）
        planning_model = get_model(explicit_model) if explicit_model else None

        # 0. 会話の継続性: 直近のタスク記録を参考情報として読み込む。
        #    履歴テキストはタスク文が過去参照（「さっき」等）を含むときだけ
        #    プロンプトに載せる。previous_output（{{previous.output}} 解決用）は
        #    プロンプトに載らないため常に用意してよい。
        recent = self._store.load_recent(_context_recent_tasks())
        context = _build_recent_context(recent) if _needs_history(task_text) else ""
        previous_output = _previous_output(recent)

        # 1. 実行計画の生成
        # 注意: 履歴コンテキストは planner には渡さない。Qwen3.6(reasoning)は
        # 履歴付きで計画させると思考がトークン上限まで発散し content が
        # 返らないことを実測で確認済み（2026-07-16）。「さっきの結果」は
        # {{previous.output}} プレースホルダで計画でき、履歴の実体は
        # executor と最終応答プロンプトだけが持てばよい。
        rejected_reason: str | None = None
        try:
            plan = self._planner.plan(task_text, planning_model=planning_model)
        except PlanRejected as exc:
            plan = Plan(steps=(), source="llm", note=str(exc))
            rejected_reason = str(exc)
            logger.warning("実行計画を拒否: %s", rejected_reason)

        # 2. モデル選択（計画の先頭ツールから従来の TaskKind を導出）
        kind = _kind_for_plan(plan)
        decision = self._router.route(
            kind, explicit_model=explicit_model, quality_first=quality_first
        )

        # 3. ステップ実行
        step_results: list[StepResult] = []
        if rejected_reason is None and plan.steps:
            step_results = execute_plan(
                plan, self._registry, task_text,
                extra_params=tool_params or {},
                previous_output=previous_output,
            )

        # 4. 最終応答
        if rejected_reason is not None:
            # 拒否時はLLMに作文させない（未実行なのに完了と述べる余地を残さない）
            llm_output = (
                "実行計画が安全ガードにより拒否されたため、何も実行していません。"
                f"理由: {rejected_reason}"
            )
            chat_stubbed = False
        else:
            messages = [ChatMessage("system", _SYSTEM_PROMPT)]
            parts = [f"タスク: {task_text}"]
            if context:
                parts.append(context)
            if step_results:
                parts.append(_build_step_report(plan, step_results))
            if len(parts) == 1:
                messages.append(ChatMessage("user", task_text))
            else:
                messages.append(ChatMessage("user", "\n\n".join(parts)))
            chat = self._client.chat(decision.model, messages)
            llm_output = chat.content
            chat_stubbed = chat.stubbed

        # 5. 集計と実行ログ保存
        executed = [r for r in step_results if not r.skipped]
        tool_ok: bool | None = None
        if step_results:
            tool_ok = bool(executed) and all(r.ok for r in executed) \
                and not any(r.skipped for r in step_results)
        stubbed = (
            chat_stubbed
            or plan.stubbed
            or any(r.stubbed for r in step_results)
        )
        first_step = plan.steps[0] if plan.steps else None

        record = TaskRecord(
            task_text=task_text,
            task_kind=kind.value,
            model_name=decision.model.name,
            route_reason=decision.reason,
            tool_name=first_step.tool if first_step else None,
            tool_action=first_step.action if first_step else None,
            tool_ok=tool_ok,
            tool_output=executed[-1].output if executed else "",
            llm_output=llm_output,
            stubbed=stubbed,
            plan_source=plan.source,
            plan_note=plan.note if rejected_reason is None else rejected_reason,
            plan=[
                {"tool": s.tool, "action": s.action, "params": s.params}
                for s in plan.steps
            ],
            step_results=[asdict(r) for r in step_results],
        )
        self._store.save(record)

        return TaskOutcome(
            task_text=task_text,
            task_kind=kind.value,
            model_name=decision.model.name,
            route_reason=decision.reason,
            plan_source=plan.source,
            plan_note=record.plan_note,
            plan_rejected=rejected_reason is not None,
            steps=tuple(step_results),
            tool_name=first_step.tool if first_step else None,
            tool_ok=tool_ok,
            tool_output=executed[-1].output if executed else None,
            llm_output=llm_output,
            stubbed=stubbed,
            record_id=record.id,
        )
