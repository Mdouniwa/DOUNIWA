"""LLMベースの実行計画（プラン）生成。

タスク文をLLMに渡し、「どのツールを・どの順で・どんな params で呼ぶか」を
JSON形式の実行計画として出力させる。利用可能なツール一覧は
registry の各アダプタ（supported_actions / action_docs）から動的に生成する。

設計原則（2026-07-16 の虚偽成功報告バグの再発防止）:
  - planner は「計画」を作るだけ。実行と結果報告は executor / core が担い、
    計画が立ったことと実行できたことを混同しない。
  - 安全ガード（最大ステップ数・書き込み系 action の回数）に反する計画は
    実行前に PlanRejected で拒否する。
  - LLM出力のJSONが解釈できない・LLM未接続(stub)の場合は、従来の
    キーワード分類（classifier.classify_task）による単一ステップ計画に
    フォールバックし、その事実を Plan.note に残す。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

from app.llm.client import ChatMessage, LLMClient
from app.llm.models import DEFAULT_MODEL, ModelSpec, get_model
from app.orchestrator.classifier import classify_task
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = 5
#: 1タスク内で許す書き込み系 action（write_actions）の回数上限。
#: これを超える計画は生成ミス・暴走の可能性が高いため実行前に拒否する。
MAX_WRITE_ACTIONS = 3


def max_plan_steps() -> int:
    try:
        return int(os.environ.get("MAX_PLAN_STEPS", DEFAULT_MAX_STEPS))
    except ValueError:
        return DEFAULT_MAX_STEPS


class PlanRejected(Exception):
    """安全ガードに反する計画。実行せず、正直にエラーとして報告する。"""


@dataclass(frozen=True)
class PlanStep:
    tool: str
    action: str
    params: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.tool}.{self.action}"


@dataclass(frozen=True)
class Plan:
    steps: tuple[PlanStep, ...]
    source: str            # "llm" | "rules"（キーワード分類フォールバック）
    note: str = ""         # フォールバック理由等の補足
    stubbed: bool = False  # 計画生成LLMが stub だったか


_PROMPT_TEMPLATE = """あなたはユーザーのタスクを実行計画(JSON)へ変換するプランナーです。

利用可能なツールと action:
<<CATALOG>>

出力規則:
- JSONオブジェクトのみを出力する。説明文・前置き・コードフェンスは書かない。
- 形式: {"steps": [{"tool": "<ツール名>", "action": "<action名>", "params": {...}}]}
- 前のステップの出力を params の値に使うときは "{{step1.output}}" のように書く（番号は1始まり）。
- 「さっきの結果」など直前のタスクの結果を params の値に使うときは "{{previous.output}}" と書く。
- テキストの要約・変換・生成が必要なときは llm.generate ステップを挟む。
- ツールが不要な雑談・単純な質問・直前の結果についての質問には {"steps": []} を返す。
- ステップ数は最大<<MAX_STEPS>>。

例1: タスク「GitHubのREADMEを要約してObsidianに『リポジトリ概要』というメモで保存して」
{"steps": [
  {"tool": "github", "action": "read_readme", "params": {}},
  {"tool": "llm", "action": "generate", "params": {"prompt": "次のREADMEを日本語で簡潔に要約してください:\\n{{step1.output}}"}},
  {"tool": "obsidian", "action": "save_note", "params": {"title": "リポジトリ概要", "body": "{{step2.output}}"}}
]}

例2: タスク「量子力学を説明して」
{"steps": []}

例3: タスク「さっきの結果をObsidianに『まとめ』というメモで保存して」
{"steps": [
  {"tool": "obsidian", "action": "save_note", "params": {"title": "まとめ", "body": "{{previous.output}}"}}
]}"""


def _build_catalog(registry: ToolRegistry) -> str:
    lines = []
    for name in registry.names():
        adapter = registry.get(name)
        for action in adapter.supported_actions:
            doc = adapter.action_docs.get(action, "")
            lines.append(f"- {name}.{action}: {doc}")
    return "\n".join(lines)


def build_planner_prompt(registry: ToolRegistry) -> str:
    return (
        _PROMPT_TEMPLATE
        .replace("<<CATALOG>>", _build_catalog(registry))
        .replace("<<MAX_STEPS>>", str(max_plan_steps()))
    )


def _extract_json(text: str) -> dict | None:
    """テキストから最初のJSONオブジェクトを取り出す。

    reasoning モデルの思考テキストやコードフェンスが混ざっても拾えるよう、
    ブレース対応で候補範囲を切り出して順に json.loads を試す。
    （JSON文字列内の {{stepN.output}} は開閉が対になっているため、
    素朴なブレース数え上げでも範囲がずれない。）
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(obj, dict):
                        return obj
                    break
        start = text.find("{", start + 1)
    return None


def _parse_steps(obj: dict, registry: ToolRegistry) -> tuple[PlanStep, ...] | None:
    """LLM出力のdictをPlanStep列に変換する。構造が不正なら None。"""
    steps_raw = obj.get("steps")
    if not isinstance(steps_raw, list):
        return None
    steps: list[PlanStep] = []
    for item in steps_raw:
        if not isinstance(item, dict):
            return None
        tool = item.get("tool")
        action = item.get("action")
        params = item.get("params") or {}
        if not isinstance(tool, str) or not isinstance(action, str) \
                or not isinstance(params, dict):
            return None
        try:
            adapter = registry.get(tool)
        except KeyError:
            logger.warning("計画に未知のツール '%s' が含まれています", tool)
            return None
        if adapter.supported_actions and action not in adapter.supported_actions:
            logger.warning("計画に未知の action '%s.%s' が含まれています", tool, action)
            return None
        steps.append(PlanStep(tool=tool, action=action, params=params))
    return tuple(steps)


def check_guards(steps: tuple[PlanStep, ...], registry: ToolRegistry) -> None:
    """安全ガード。違反する計画は実行前に PlanRejected で拒否する。"""
    limit = max_plan_steps()
    if len(steps) > limit:
        raise PlanRejected(
            f"計画が{len(steps)}ステップあり、上限{limit}を超えています"
        )
    writes = [s for s in steps if s.action in registry.get(s.tool).write_actions]
    if len(writes) > MAX_WRITE_ACTIONS:
        raise PlanRejected(
            f"書き込み系actionが{len(writes)}回計画されており、"
            f"上限{MAX_WRITE_ACTIONS}回を超えています"
        )


class Planner:
    def __init__(
        self,
        client: LLMClient,
        registry: ToolRegistry,
        model: ModelSpec | None = None,
    ) -> None:
        self._client = client
        self._registry = registry
        self._model = model

    def plan(
        self,
        task_text: str,
        planning_model: ModelSpec | None = None,
        context: str = "",
    ) -> Plan:
        """タスク文から実行計画を生成する。

        Args:
            context: 直近のタスク履歴等の参考情報（「さっきの結果」の解釈用）。

        Raises:
            PlanRejected: 安全ガード（ステップ数・書き込み回数）違反。
        """
        model = planning_model or self._model or get_model(DEFAULT_MODEL)
        user_message = f"タスク: {task_text}"
        if context:
            user_message += f"\n\n{context}"
        chat = self._client.chat(
            model,
            [
                ChatMessage("system", build_planner_prompt(self._registry)),
                ChatMessage("user", user_message),
            ],
            temperature=0.1,
        )
        if chat.stubbed:
            return self._fallback(
                task_text,
                note="計画生成LLMが未接続(stub)のためキーワード分類にフォールバック",
                stubbed=True,
            )

        obj = _extract_json(chat.content)
        steps = _parse_steps(obj, self._registry) if obj is not None else None
        if steps is None:
            logger.warning(
                "計画JSONを解釈できませんでした。キーワード分類にフォールバックします。"
                " LLM出力(先頭200字): %.200s", chat.content,
            )
            return self._fallback(
                task_text,
                note="LLM出力の計画JSONを解釈できずキーワード分類にフォールバック",
                stubbed=False,
            )

        check_guards(steps, self._registry)
        logger.info(
            "実行計画(llm): %s", " -> ".join(s.label for s in steps) or "(ステップなし)"
        )
        return Plan(steps=steps, source="llm")

    def _fallback(self, task_text: str, note: str, stubbed: bool) -> Plan:
        c = classify_task(task_text)
        steps: tuple[PlanStep, ...] = ()
        if c.tool_name and c.tool_action:
            steps = (PlanStep(tool=c.tool_name, action=c.tool_action, params={}),)
        logger.info("実行計画(rules): %s / %s",
                    " -> ".join(s.label for s in steps) or "(ステップなし)", note)
        return Plan(steps=steps, source="rules", note=note, stubbed=stubbed)
