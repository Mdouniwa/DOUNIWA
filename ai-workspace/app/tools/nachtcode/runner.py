"""Nacht Code 専用の実行経路（CLI用）。

kuro·console のオーケストレーターとは独立した、コーディングタスク専用の
一本線。計画→実行→結果表示のすべてで以下を守る:

  - 対象ディレクトリは CLI の --dir で人間が明示したものだけを使う。
    LLMの計画が別の dir を書いても、実行前に必ず --dir で上書きする。
  - 対象が git リポジトリでない場合、変更の巻き戻し手段がないため
    実行前に中断して人間に確認させる（--yes で続行を明示）。
  - 計画JSONを解釈できない場合はキーワード推測にフォールバックせず、
    正直にエラーで止まる（推測でコードを書き換えない）。
  - 最終要約はLLMに作文させず、ステップ実行結果から機械的に組み立てる。
"""

from __future__ import annotations

import logging
import os

from app.llm.client import ChatMessage, LLMClient
from app.llm.models import DEFAULT_MODEL, get_model
from app.orchestrator.executor import StepResult, execute_plan
from app.orchestrator.planner import (
    Plan,
    PlanRejected,
    PlanStep,
    _extract_json,
    _parse_steps,
    check_guards,
)
from app.tools.base import ToolRequest
from app.tools.llm_gen.adapter import LLMGenAdapter
from app.tools.nachtcode.adapter import NachtCodeAdapter, validate_project_dir
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """あなたは "Nacht Code"、対象プロジェクト内のコードを読み書きする\
コーディングエージェントのプランナーです。

利用可能な action:
<<CATALOG>>

対象プロジェクトのファイル一覧:
<<LISTING>>

出力規則:
- JSONオブジェクトのみを出力する。説明文・コードフェンスは書かない。
- 形式: {"steps": [{"tool": "<ツール名>", "action": "<action名>", "params": {...}}]}
- params に "dir" は書かない（システムが自動設定する）。
- 前のステップの出力を使うときは "{{step1.output}}" のように書く（1始まり）。
- 重要: コード本文をこのJSONの中に直接書かない。コードの生成・変更は
  llm.generate ステップに任せ、その出力を {{stepN.output}} で
  edit_file / create_file の "content" に渡す。
- 深く考えず、下の例の形をそのまま使う。
- ファイルの削除・移動・git push・外部コマンドは実行できない（actionが存在しない）。
- ステップ数は最大<<MAX_STEPS>>。

例1: タスク「hello.py の関数に docstring を追加してテストして」
{"steps": [
  {"tool": "nachtcode", "action": "read_file", "params": {"path": "hello.py"}},
  {"tool": "llm", "action": "generate", "params": {"prompt": "次のPythonファイルの各関数に日本語のdocstringを追加した、ファイル全体の完全な内容だけを出力してください。説明文やコードフェンスは書かないでください。\\n{{step1.output}}"}},
  {"tool": "nachtcode", "action": "edit_file", "params": {"path": "hello.py", "content": "{{step2.output}}"}},
  {"tool": "nachtcode", "action": "run_tests", "params": {}}
]}

例2: 定数変更のような小さな置換は old_string/new_string 方式でよい
{"steps": [
  {"tool": "nachtcode", "action": "edit_file", "params": {"path": "util.py", "old_string": "MAX = 5", "new_string": "MAX = 10"}},
  {"tool": "nachtcode", "action": "run_tests", "params": {}}
]}"""

#: 計画生成はコード片の検討で思考が長くなりがちなので、上限を広めに取る
_PLANNING_MAX_TOKENS = 8192


def _build_registry(client: LLMClient) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(NachtCodeAdapter())
    registry.register(LLMGenAdapter(client))
    return registry


def _catalog(registry: ToolRegistry) -> str:
    lines = []
    for name in registry.names():
        adapter = registry.get(name)
        for action in adapter.supported_actions:
            lines.append(f"- {name}.{action}: {adapter.action_docs.get(action, '')}")
    return "\n".join(lines)


def plan_coding_task(
    client: LLMClient,
    registry: ToolRegistry,
    root: str,
    task_text: str,
    model_name: str | None = None,
) -> Plan:
    """コーディングタスクの実行計画を生成する。

    解釈失敗時はフォールバックせず PlanRejected を投げる
    （推測でコードを書き換えないため）。
    """
    listing = NachtCodeAdapter().execute(
        ToolRequest(action="list_files", params={"dir": root})
    ).output[:4000]
    from app.orchestrator.planner import max_plan_steps
    system = (
        _PROMPT_TEMPLATE
        .replace("<<CATALOG>>", _catalog(registry))
        .replace("<<LISTING>>", listing)
        .replace("<<MAX_STEPS>>", str(max_plan_steps()))
    )
    model = get_model(model_name or DEFAULT_MODEL)
    # 温度は 0.6: Qwen3系のthinkingモードは低温度だと思考が無限反復に
    # 退化する（公式推奨値に合わせる。2026-07-17 実測で反復ループを確認）
    chat = client.chat(
        model,
        [ChatMessage("system", system), ChatMessage("user", f"タスク: {task_text}")],
        temperature=0.6,
        max_tokens=_PLANNING_MAX_TOKENS,
    )
    if chat.stubbed:
        raise PlanRejected("計画生成LLMが未接続(stub)のため実行しません")
    obj = _extract_json(chat.content)
    steps = _parse_steps(obj, registry) if obj is not None else None
    if steps is None:
        raise PlanRejected(
            "計画JSONを解釈できませんでした（推測でコードは変更しません）。"
            f" LLM出力(先頭200字): {chat.content[:200]}"
        )
    # 対象ディレクトリは人間が --dir で指定したものを強制する。
    # LLMが params に別の dir を書いても必ず上書きする（安全ガード）。
    forced = tuple(
        PlanStep(s.tool, s.action, {**s.params, "dir": root})
        if s.tool == "nachtcode" else s
        for s in steps
    )
    check_guards(forced, registry)
    return Plan(steps=forced, source="llm")


def run_nachtcode_task(
    target_dir: str,
    task_text: str,
    assume_yes: bool = False,
    model_name: str | None = None,
) -> int:
    root, error = validate_project_dir(target_dir)
    if error:
        print(f"error: {error}")
        return 2

    is_git = (root / ".git").exists()
    print("=" * 60)
    print("Nacht Code")
    print(f"対象DIR   : {root}" + ("（git管理）" if is_git else "（git管理外）"))
    print(f"タスク    : {task_text}")
    print("方針      : 削除・移動・git push・外部コマンドは実装されていません。")
    print("            変更はすべて監査ログ（NACHTCODE_AUDIT_DIR）に diff で残ります。")
    if not is_git and not assume_yes:
        print("=" * 60)
        print("中断: 対象が git リポジトリではないため、変更の巻き戻し手段がありません。")
        print("バックアップがあることを確認のうえ、--yes を付けて再実行してください。")
        return 2

    client = LLMClient()
    registry = _build_registry(client)

    try:
        plan = plan_coding_task(client, registry, str(root), task_text, model_name)
    except PlanRejected as exc:
        print("=" * 60)
        print(f"計画を実行しません: {exc}")
        return 1

    print("実行計画  :")
    for i, step in enumerate(plan.steps, start=1):
        summary = step.params.get("path") or step.params.get("message") or ""
        print(f"  {i}. {step.label} {summary}")
    print("=" * 60)

    results = execute_plan(plan, registry, task_text)

    ok = failed = skipped = 0
    for r in results:
        print(f"Step {r.index}/{len(results)}: {r.label} → {r.status}")
        if r.skipped:
            skipped += 1
            continue
        if r.ok:
            ok += 1
        else:
            failed += 1
        detail = r.data.get("diff") if isinstance(r.data, dict) else None
        text = detail or r.output
        for line in text.splitlines()[:40]:
            print(f"    {line}")
    print("=" * 60)
    audit_dir = os.environ.get("NACHTCODE_AUDIT_DIR", "data/nachtcode")
    print(f"結果      : 成功{ok} / 失敗{failed} / スキップ{skipped}")
    print(f"監査ログ  : {audit_dir}/audit-*.jsonl")
    return 0 if failed == 0 else 1
