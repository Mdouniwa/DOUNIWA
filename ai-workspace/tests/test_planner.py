"""Planner のJSON解釈・フォールバック・安全ガードの検証。"""

from __future__ import annotations

import pytest

from app.llm.client import ChatResult
from app.orchestrator.planner import (
    MAX_WRITE_ACTIONS,
    Plan,
    Planner,
    PlanRejected,
    PlanStep,
    _extract_json,
    check_guards,
)
from app.tools.llm_gen.adapter import LLMGenAdapter
from app.tools.registry import build_default_registry


class _FakeLLM:
    """固定の応答を返す偽クライアント。"""

    def __init__(self, content: str, stubbed: bool = False) -> None:
        self._content = content
        self._stubbed = stubbed

    def chat(self, model, messages, temperature=0.3) -> ChatResult:
        return ChatResult(
            model_name=model.name, content=self._content, stubbed=self._stubbed
        )


@pytest.fixture
def registry():
    reg = build_default_registry()
    reg.register(LLMGenAdapter(client=None))  # 計画検証にはclient不要
    return reg


def test_extract_json_handles_fences_and_placeholders():
    text = (
        "思考: まずREADMEを取る…\n"
        "```json\n"
        '{"steps": [{"tool": "obsidian", "action": "save_note",'
        ' "params": {"body": "{{step1.output}}"}}]}\n'
        "```"
    )
    obj = _extract_json(text)
    assert obj is not None
    assert obj["steps"][0]["params"]["body"] == "{{step1.output}}"


def test_plan_parses_llm_json(registry):
    content = (
        '{"steps": ['
        '{"tool": "github", "action": "read_readme", "params": {}},'
        '{"tool": "llm", "action": "generate",'
        ' "params": {"prompt": "要約: {{step1.output}}"}},'
        '{"tool": "obsidian", "action": "save_note",'
        ' "params": {"title": "T", "body": "{{step2.output}}"}}'
        "]}"
    )
    plan = Planner(_FakeLLM(content), registry).plan("READMEを要約して保存して")
    assert plan.source == "llm"
    assert [s.label for s in plan.steps] == \
        ["github.read_readme", "llm.generate", "obsidian.save_note"]


def test_plan_empty_steps_for_chat(registry):
    # ツール語彙(github)を含むので高速パスは通らず、LLMが空計画を返すケース
    plan = Planner(_FakeLLM('{"steps": []}'), registry).plan("GitHubって何のサービス?")
    assert plan.source == "llm"
    assert plan.steps == ()


class _ExplodingLLM:
    """呼ばれたらテスト失敗にする偽クライアント（高速パスの検証用）。"""

    def chat(self, model, messages, temperature=0.3):
        raise AssertionError("高速パスのはずが planner がLLMを呼び出した")


def test_fast_path_skips_planner_llm_for_plain_chat(registry):
    plan = Planner(_ExplodingLLM(), registry).plan("こんにちは")
    assert plan.source == "fast"
    assert plan.steps == ()
    assert plan.stubbed is False


def test_fast_path_not_taken_when_tool_vocab_present(registry):
    # ツール語彙があれば必ず planner（LLM）を通る
    content = '{"steps": [{"tool": "obsidian", "action": "save_note", "params": {}}]}'
    plan = Planner(_FakeLLM(content), registry).plan("Obsidianにメモを保存して")
    assert plan.source == "llm"
    assert [s.label for s in plan.steps] == ["obsidian.save_note"]


def test_plan_falls_back_to_rules_on_broken_json(registry):
    plan = Planner(_FakeLLM("すみません、JSONは書けません。"), registry).plan(
        "Obsidianにメモを保存して"
    )
    assert plan.source == "rules"
    assert plan.note  # フォールバック理由が残る
    assert [s.label for s in plan.steps] == ["obsidian.save_note"]


def test_plan_falls_back_to_rules_on_unknown_tool(registry):
    content = '{"steps": [{"tool": "slack", "action": "post", "params": {}}]}'
    plan = Planner(_FakeLLM(content), registry).plan("Obsidianにメモを保存して")
    assert plan.source == "rules"


def test_plan_falls_back_when_llm_stubbed(registry):
    plan = Planner(_FakeLLM("[stub] dummy", stubbed=True), registry).plan(
        "このリポジトリのREADMEを読んで"
    )
    assert plan.source == "rules"
    assert plan.stubbed is True
    assert [s.label for s in plan.steps] == ["github.read_readme"]


def test_guard_rejects_too_many_steps(registry, monkeypatch):
    monkeypatch.setenv("MAX_PLAN_STEPS", "5")
    steps = tuple(
        PlanStep("github", "read_readme", {}) for _ in range(6)
    )
    with pytest.raises(PlanRejected, match="上限5"):
        check_guards(steps, registry)


def test_guard_rejects_too_many_write_actions(registry):
    steps = tuple(
        PlanStep("obsidian", "save_note", {"title": f"t{i}"})
        for i in range(MAX_WRITE_ACTIONS + 1)
    )
    with pytest.raises(PlanRejected, match="書き込み系"):
        check_guards(steps, registry)


def test_guard_allows_reads_beyond_write_limit(registry):
    # 読み取り系は書き込み回数制限の対象外
    steps = tuple(PlanStep("github", "read_readme", {}) for _ in range(4))
    check_guards(steps, registry)  # 例外が出ないこと


def test_planner_raises_plan_rejected_through_plan(registry):
    content = (
        '{"steps": ['
        + ",".join(
            '{"tool": "obsidian", "action": "save_note", "params": {}}'
            for _ in range(4)
        )
        + "]}"
    )
    with pytest.raises(PlanRejected):
        Planner(_FakeLLM(content), registry).plan("メモを大量に保存して")
