"""executor のステップ実行・出力差し込み・失敗ポリシー・時間上限の検証。"""

from __future__ import annotations

from app.orchestrator.executor import execute_plan
from app.orchestrator.planner import Plan, PlanStep
from app.tools.base import ToolAdapter, ToolRequest, ToolResult
from app.tools.registry import ToolRegistry


class _EchoTool(ToolAdapter):
    name = "echo"
    supported_actions = ("say", "fail")

    def execute(self, request: ToolRequest) -> ToolResult:
        if request.action == "fail":
            return ToolResult(ok=False, output="boom")
        return ToolResult(ok=True, output=f"echo:{request.params.get('text', '')}")


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    return reg


def _plan(*steps: PlanStep) -> Plan:
    return Plan(steps=steps, source="llm")


def test_placeholder_chains_previous_output(tmp_path, monkeypatch):
    monkeypatch.setenv("EXECUTOR_LOG_DIR", str(tmp_path))
    plan = _plan(
        PlanStep("echo", "say", {"text": "hello"}),
        PlanStep("echo", "say", {"text": "got {{step1.output}}"}),
    )
    results = execute_plan(plan, _registry(), "テスト")
    assert results[0].output == "echo:hello"
    assert results[1].output == "echo:got echo:hello"
    assert all(r.ok and not r.skipped for r in results)


def test_dependent_step_skipped_but_independent_continues(tmp_path, monkeypatch):
    monkeypatch.setenv("EXECUTOR_LOG_DIR", str(tmp_path))
    plan = _plan(
        PlanStep("echo", "fail", {}),
        PlanStep("echo", "say", {"text": "{{step1.output}}"}),  # 失敗に依存
        PlanStep("echo", "say", {"text": "independent"}),       # 独立
    )
    results = execute_plan(plan, _registry(), "テスト")
    assert results[0].ok is False and results[0].skipped is False
    assert results[1].skipped is True
    assert "step1" in results[1].skip_reason
    assert results[2].ok is True and results[2].skipped is False


def test_skip_cascades_through_dependency_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("EXECUTOR_LOG_DIR", str(tmp_path))
    plan = _plan(
        PlanStep("echo", "fail", {}),
        PlanStep("echo", "say", {"text": "{{step1.output}}"}),
        PlanStep("echo", "say", {"text": "{{step2.output}}"}),  # スキップに依存
    )
    results = execute_plan(plan, _registry(), "テスト")
    assert results[1].skipped is True
    assert results[2].skipped is True


def test_forward_reference_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("EXECUTOR_LOG_DIR", str(tmp_path))
    plan = _plan(
        PlanStep("echo", "say", {"text": "{{step3.output}}"}),  # 未来の参照
        PlanStep("echo", "say", {"text": "ok"}),
    )
    results = execute_plan(plan, _registry(), "テスト")
    assert results[0].skipped is True
    assert "不正なステップ参照" in results[0].skip_reason
    assert results[1].ok is True


def test_time_budget_skips_remaining_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("EXECUTOR_LOG_DIR", str(tmp_path))
    plan = _plan(
        PlanStep("echo", "say", {"text": "a"}),
        PlanStep("echo", "say", {"text": "b"}),
    )
    # 上限を負値にして「開始時点で超過」させ、全ステップがスキップされることを見る
    results = execute_plan(plan, _registry(), "テスト", max_duration_s=-1.0)
    assert all(r.skipped for r in results)
    assert all("実行時間上限" in r.skip_reason for r in results)


def test_unknown_action_is_reported_as_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("EXECUTOR_LOG_DIR", str(tmp_path))
    plan = _plan(PlanStep("echo", "unknown", {}))
    results = execute_plan(plan, _registry(), "テスト")
    assert results[0].ok is False
    assert results[0].skipped is False
    assert "サポートしません" in results[0].output
