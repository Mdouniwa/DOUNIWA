"""end-to-end の一本線が stub モードで通ることの検証。

外部接続なし（環境変数未設定）で実行できる。
"""

from __future__ import annotations

import json

import pytest

from app.memory.store import MemoryStore
from app.orchestrator.classifier import TaskKind, classify_task
from app.orchestrator.core import Orchestrator


@pytest.fixture
def orchestrator(tmp_path, monkeypatch):
    # 実接続系の環境変数を確実に外し、ログは一時ディレクトリへ
    for var in ("LOCAL_LLM_BASE_URL", "GITHUB_TOKEN", "OBSIDIAN_VAULT_PATH",
                "N8N_WEBHOOK_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return Orchestrator(store=MemoryStore(base_dir=tmp_path)), tmp_path


def test_classify_task_routes_to_expected_tools():
    assert classify_task("このリポジトリのREADMEを読んで").kind == TaskKind.CODE
    assert classify_task("Obsidianにメモを保存して").kind == TaskKind.WRITE_NOTE
    assert classify_task("n8nのWebhookを叩いて").kind == TaskKind.AUTOMATION
    assert classify_task("ブラウザで開いて").kind == TaskKind.BROWSER
    assert classify_task("量子力学を説明して").kind == TaskKind.GENERAL


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
