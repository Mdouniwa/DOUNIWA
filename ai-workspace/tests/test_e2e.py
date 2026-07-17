"""end-to-end の一本線が stub モードで通ることの検証。

外部接続なし（環境変数未設定）で実行できる。
"""

from __future__ import annotations

import json

import pytest

from app.llm.client import ChatMessage, ChatResult
from app.memory.store import MemoryStore
from app.orchestrator.classifier import TaskKind, classify_task
from app.orchestrator.core import Orchestrator


def _isolate_env(tmp_path, monkeypatch):
    """実接続系の環境変数を外し、executor ログも一時ディレクトリへ向ける。"""
    for var in ("LOCAL_LLM_BASE_URL", "GITHUB_TOKEN", "OBSIDIAN_VAULT_PATH",
                "N8N_WEBHOOK_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("EXECUTOR_LOG_DIR", str(tmp_path / "logs"))


@pytest.fixture
def orchestrator(tmp_path, monkeypatch):
    _isolate_env(tmp_path, monkeypatch)
    return Orchestrator(store=MemoryStore(base_dir=tmp_path)), tmp_path


def test_classify_task_routes_to_expected_tools():
    assert classify_task("このリポジトリのREADMEを読んで").kind == TaskKind.CODE
    assert classify_task("Obsidianにメモを保存して").kind == TaskKind.WRITE_NOTE
    assert classify_task("n8nのWebhookを叩いて").kind == TaskKind.AUTOMATION
    assert classify_task("ブラウザで開いて").kind == TaskKind.BROWSER
    assert classify_task("量子力学を説明して").kind == TaskKind.GENERAL


def test_classify_ignores_quoted_payload():
    """『…』内はメモのタイトル（データ）であり、タスクの意図ではない。

    回帰テスト: タイトルに GitHub・n8n を含むメモ保存指示が
    code/github に誤分類され、READMEを取得したうえで
    「保存しました」と虚偽報告された問題（2026-07-15）。
    """
    c = classify_task("Obsidianに『実装テスト:GitHub・n8n配線確認完了』というメモを保存して")
    assert c.kind == TaskKind.WRITE_NOTE
    assert c.tool_name == "obsidian"


def test_classify_prefers_rule_with_most_keyword_hits():
    c = classify_task("GitHubの調査結果をObsidianにメモとして保存して")
    assert c.kind == TaskKind.WRITE_NOTE


class _RecordingClient:
    """LLMに渡された messages と呼び出し回数を記録する偽クライアント。"""

    def __init__(self) -> None:
        self.messages: list[ChatMessage] = []
        self.calls = 0

    def chat(self, model, messages, temperature=0.3, max_tokens=None) -> ChatResult:
        self.calls += 1
        self.messages = messages
        return ChatResult(model_name=model.name, content="ok", stubbed=True)


def test_tool_status_is_passed_to_llm_prompt(tmp_path, monkeypatch):
    """ステップごとの成否・stub状態が最終応答プロンプトに明示されること。

    回帰テスト: 実行結果の成否がLLMに渡らず、未実行の操作を
    「完了した」と報告してしまう問題への対策の検証。
    """
    _isolate_env(tmp_path, monkeypatch)
    client = _RecordingClient()
    orch = Orchestrator(client=client, store=MemoryStore(base_dir=tmp_path))

    outcome = orch.run("Obsidianにメモを保存して")  # vault未設定 → stub

    assert outcome.tool_ok is True
    assert outcome.stubbed is True
    system = client.messages[0].content
    assert "完了したと述べてはいけません" in system
    prompt = client.messages[-1].content
    assert "各ステップの実行結果" in prompt
    assert "実際には実行されていない" in prompt


def test_fast_path_uses_single_llm_call_for_plain_chat(tmp_path, monkeypatch):
    """ツール語彙のない入力は planner を省き、LLM呼び出しが1回で済むこと。"""
    _isolate_env(tmp_path, monkeypatch)
    client = _RecordingClient()
    orch = Orchestrator(client=client, store=MemoryStore(base_dir=tmp_path))

    outcome = orch.run("こんにちは")

    assert outcome.plan_source == "fast"
    assert outcome.steps == ()
    assert client.calls == 1  # 最終応答のみ（計画生成のLLM呼び出しなし）


def test_e2e_multistep_plan_chains_outputs(tmp_path, monkeypatch):
    """複数ステップ計画: {{stepN.output}} が後段に差し込まれて実行されること。"""
    _isolate_env(tmp_path, monkeypatch)
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    monkeypatch.setenv("OBSIDIAN_NOTE_FOLDER", "inbox")

    from app.orchestrator.planner import Plan, PlanStep

    class _FixedPlanner:
        def plan(self, task_text, planning_model=None, context=""):
            return Plan(
                steps=(
                    PlanStep("github", "read_readme", {}),
                    PlanStep("obsidian", "save_note",
                             {"title": "連結テスト", "body": "{{step1.output}}"}),
                ),
                source="llm",
            )

    orch = Orchestrator(
        store=MemoryStore(base_dir=tmp_path / "mem"), planner=_FixedPlanner()
    )
    outcome = orch.run("READMEを取ってメモして")

    assert [s.label for s in outcome.steps] == \
        ["github.read_readme", "obsidian.save_note"]
    assert outcome.steps[1].skipped is False
    assert outcome.steps[1].ok is True
    files = list((vault / "inbox").glob("*.md"))
    assert len(files) == 1
    # step1（github stub）の出力が step2 の本文に差し込まれている
    assert "[stub:github]" in files[0].read_text(encoding="utf-8")
    assert outcome.tool_ok is True
    assert outcome.stubbed is True  # github が stub なのでタスク全体も stub 扱い


def test_e2e_rejected_plan_reports_honestly(tmp_path, monkeypatch):
    """安全ガードで拒否された計画は何も実行せず、その旨を明記すること。"""
    _isolate_env(tmp_path, monkeypatch)

    from app.orchestrator.planner import PlanRejected

    class _RejectingPlanner:
        def plan(self, task_text, planning_model=None, context=""):
            raise PlanRejected("テスト用の拒否理由")

    orch = Orchestrator(
        store=MemoryStore(base_dir=tmp_path), planner=_RejectingPlanner()
    )
    outcome = orch.run("なんでもいいから全部やって")

    assert outcome.plan_rejected is True
    assert outcome.steps == ()
    assert outcome.tool_ok is None
    assert "何も実行していません" in outcome.llm_output
    assert "テスト用の拒否理由" in outcome.llm_output


def test_e2e_github_task_stub(orchestrator):
    orch, tmp_path = orchestrator
    outcome = orch.run("このリポジトリのREADMEを読んで改善点を出して")

    assert outcome.task_kind == "code"
    assert outcome.model_name == "qwen-35b"
    assert outcome.tool_name == "github"
    assert outcome.stubbed is True
    assert outcome.llm_output

    # 実行ログが JSONL に1行書かれている
    files = list(tmp_path.glob("runs-*.jsonl"))
    assert len(files) == 1
    record = json.loads(files[0].read_text().strip())
    assert record["id"] == outcome.record_id
    assert record["task_kind"] == "code"


def test_e2e_quality_flag_selects_70b(orchestrator):
    orch, _ = orchestrator
    outcome = orch.run("アーキテクチャをレビューして", quality_first=True)
    assert outcome.model_name == "llama-70b"


def test_e2e_explicit_model_overrides_policy(orchestrator):
    orch, _ = orchestrator
    outcome = orch.run("Obsidianにメモを保存して", explicit_model="cloud-claude")
    assert outcome.model_name == "cloud-claude"
    assert outcome.tool_name == "obsidian"


def test_unknown_model_raises(orchestrator):
    orch, _ = orchestrator
    with pytest.raises(KeyError):
        orch.run("こんにちは", explicit_model="gpt-99")


# ----------------------------------------------------------------------
# Phase B: 会話の継続性
# ----------------------------------------------------------------------

def _seed_record(store: MemoryStore, task_text: str, llm_output: str,
                 session_id: str = "") -> None:
    from app.memory.store import TaskRecord
    store.save(TaskRecord(
        task_text=task_text, task_kind="general", model_name="qwen-35b",
        route_reason="test", tool_name=None, tool_action=None,
        tool_output="", llm_output=llm_output, stubbed=False,
        session_id=session_id,
    ))


def test_load_recent_returns_latest_in_order(tmp_path):
    store = MemoryStore(base_dir=tmp_path)
    for i in range(5):
        _seed_record(store, f"タスク{i}", f"結果{i}")
    recent = store.load_recent(3)
    assert [r["task_text"] for r in recent] == ["タスク2", "タスク3", "タスク4"]
    assert store.load_recent(0) == []


def test_recent_context_is_passed_to_prompts(tmp_path, monkeypatch):
    """直近タスクの結果が最終応答プロンプトに渡ること。"""
    _isolate_env(tmp_path, monkeypatch)
    store = MemoryStore(base_dir=tmp_path)
    _seed_record(store, "READMEを要約して", "前回の要約結果テキストです")

    client = _RecordingClient()
    orch = Orchestrator(client=client, store=store)
    orch.run("さっきの結果をもう一度教えて")  # ツール不要 → steps なし

    prompt = client.messages[-1].content
    assert "直近のタスク履歴" in prompt
    assert "前回の要約結果テキストです" in prompt
    system = client.messages[0].content
    assert "直近のタスク履歴" in system  # 履歴を今回の実行と混同しない制約


def test_continuity_confined_to_same_session(tmp_path, monkeypatch):
    """「さっきの結果」の参照対象が同一セッションに限定されること。

    他の会話（セッションB）のタスクがコンテキストへ混入しないことの検証。
    """
    _isolate_env(tmp_path, monkeypatch)
    store = MemoryStore(base_dir=tmp_path)
    _seed_record(store, "会話Aのタスク", "会話Aの結果テキスト", session_id="sess-a")
    _seed_record(store, "会話Bのタスク", "会話Bの結果テキスト", session_id="sess-b")

    client = _RecordingClient()
    orch = Orchestrator(client=client, store=store)
    orch.run("さっきの結果をもう一度教えて", session_id="sess-a")

    prompt = client.messages[-1].content
    assert "会話Aの結果テキスト" in prompt
    assert "会話Bの結果テキスト" not in prompt


def test_history_not_included_without_reference_words(tmp_path, monkeypatch):
    """過去参照語のないタスクには履歴を渡さない（Qwenの思考発散対策）。"""
    _isolate_env(tmp_path, monkeypatch)
    store = MemoryStore(base_dir=tmp_path)
    _seed_record(store, "READMEを要約して", "前回の要約結果テキストです")

    client = _RecordingClient()
    orch = Orchestrator(client=client, store=store)
    orch.run("量子力学を説明して")

    prompt = client.messages[-1].content
    assert "直近のタスク履歴" not in prompt
    assert "前回の要約結果テキストです" not in prompt
