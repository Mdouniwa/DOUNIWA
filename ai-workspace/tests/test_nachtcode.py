"""Nacht Code アダプタの権限ガード・各アクションの検証。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.llm.client import ChatResult
from app.orchestrator.planner import PlanRejected
from app.tools.base import ToolRequest
from app.tools.nachtcode.adapter import NachtCodeAdapter, validate_project_dir
from app.tools.nachtcode.runner import _build_registry, plan_coding_task


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("NACHTCODE_AUDIT_DIR", str(tmp_path / "audit"))
    root = tmp_path / "proj"
    root.mkdir()
    (root / "hello.py").write_text(
        "def hello():\n    return 'hello'\n", encoding="utf-8"
    )
    (root / "test_hello.py").write_text(
        "from hello import hello\n\n\ndef test_hello():\n    assert hello() == 'hello'\n",
        encoding="utf-8",
    )
    return root


def _req(action: str, root: Path, **params) -> ToolRequest:
    return ToolRequest(action=action, params={"dir": str(root), **params},
                       task_text="テスト")


# ----------------------------------------------------------------------
# 対象ディレクトリの安全ガード
# ----------------------------------------------------------------------

def test_dangerous_dirs_are_rejected():
    home = str(Path.home())
    for raw in ["/", "/etc", "/usr/local", home, home + "/Library",
                "/System", "/tmp", "relative/path", ""]:
        resolved, error = validate_project_dir(raw)
        assert resolved is None, f"{raw} が許可されてしまった"
        assert error


def test_nonexistent_dir_is_rejected(tmp_path):
    resolved, error = validate_project_dir(str(tmp_path / "no-such-dir"))
    assert resolved is None
    assert "存在しません" in error


def test_tmp_subdir_is_allowed(project):
    resolved, error = validate_project_dir(str(project))
    assert error == ""
    assert resolved == project.resolve()


def test_path_traversal_is_rejected(project, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("外部ファイル", encoding="utf-8")
    for bad in ["../outside.txt", str(outside), "a/../../outside.txt"]:
        result = NachtCodeAdapter().execute(
            _req("edit_file", project, path=bad,
                 old_string="外部", new_string="改ざん")
        )
        assert result.ok is False, f"{bad} が許可されてしまった"
        assert "外は操作できません" in result.output
    assert outside.read_text(encoding="utf-8") == "外部ファイル"  # 無傷


def test_symlink_escape_is_rejected(project, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (project / "link.txt").symlink_to(outside)
    result = NachtCodeAdapter().execute(
        _req("edit_file", project, path="link.txt",
             old_string="secret", new_string="pwned")
    )
    assert result.ok is False
    assert outside.read_text(encoding="utf-8") == "secret"


def test_no_dangerous_actions_exist():
    """削除・移動・push・任意コマンドは action として存在しないこと。"""
    actions = set(NachtCodeAdapter.supported_actions)
    for banned in ("delete_file", "remove_file", "move_file", "git_push",
                   "run_command", "shell", "install"):
        assert banned not in actions


# ----------------------------------------------------------------------
# 各アクション
# ----------------------------------------------------------------------

def test_read_and_list(project):
    adapter = NachtCodeAdapter()
    listed = adapter.execute(_req("list_files", project))
    assert listed.ok and "hello.py" in listed.output

    read = adapter.execute(_req("read_file", project, path="hello.py"))
    assert read.ok and "def hello():" in read.output


def test_edit_file_applies_change_and_records_diff(project, tmp_path):
    result = NachtCodeAdapter().execute(
        _req("edit_file", project, path="hello.py",
             old_string="def hello():",
             new_string="def hello():\n    \"\"\"あいさつを返す。\"\"\"")
    )
    assert result.ok is True
    text = (project / "hello.py").read_text(encoding="utf-8")
    assert 'あいさつを返す' in text
    assert "+" in result.data["diff"] and "-" in result.data["diff"]
    # 監査ログに diff が残る
    audit_files = list((tmp_path / "audit").glob("audit-*.jsonl"))
    assert len(audit_files) == 1
    entry = json.loads(audit_files[0].read_text(encoding="utf-8").splitlines()[-1])
    assert entry["action"] == "edit_file"
    assert entry["path"] == "hello.py"
    assert "あいさつ" in entry["diff"]


def test_edit_file_requires_unique_old_string(project):
    (project / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    result = NachtCodeAdapter().execute(
        _req("edit_file", project, path="dup.py",
             old_string="x = 1", new_string="x = 2")
    )
    assert result.ok is False
    assert "一意でない" in result.output
    assert (project / "dup.py").read_text(encoding="utf-8") == "x = 1\nx = 1\n"


def test_create_file_refuses_overwrite(project):
    adapter = NachtCodeAdapter()
    created = adapter.execute(
        _req("create_file", project, path="new/util.py", content="VALUE = 1\n")
    )
    assert created.ok is True
    assert (project / "new" / "util.py").read_text(encoding="utf-8") == "VALUE = 1\n"

    again = adapter.execute(
        _req("create_file", project, path="hello.py", content="上書き")
    )
    assert again.ok is False
    assert "上書きしません" in again.output


def test_run_tests_executes_pytest(project):
    result = NachtCodeAdapter().execute(_req("run_tests", project))
    assert result.ok is True
    assert result.data["exit_code"] == 0


def test_git_commit_requires_repo_and_never_pushes(project):
    adapter = NachtCodeAdapter()
    no_repo = adapter.execute(_req("git_commit", project, message="test"))
    assert no_repo.ok is False
    assert "git リポジトリではない" in no_repo.output

    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=project)
    subprocess.run(["git", "config", "user.name", "t"], cwd=project)
    committed = adapter.execute(_req("git_commit", project, message="初回"))
    assert committed.ok is True
    assert "push はしません" in committed.output


def test_edit_content_mode_strips_fences_and_wrapper_text(project):
    adapter = NachtCodeAdapter()
    wrapped = (
        "以下が、docstringを追加した完全なコードです。\n\n"
        "```python\ndef greet(name):\n    \"\"\"あいさつ。\"\"\"\n"
        "    return f\"こんにちは、{name}さん\"\n```\n"
    )
    result = adapter.execute(
        _req("edit_file", project, path="hello.py", content=wrapped)
    )
    assert result.ok is True
    text = (project / "hello.py").read_text(encoding="utf-8")
    assert "```" not in text
    assert "以下が" not in text
    assert text.startswith("def greet(name):")


# ----------------------------------------------------------------------
# CLI経路の計画（dir の強制上書き・解釈失敗時の停止）
# ----------------------------------------------------------------------

class _FakeLLM:
    def __init__(self, content: str, stubbed: bool = False) -> None:
        self._content = content
        self._stubbed = stubbed

    def chat(self, model, messages, temperature=0.3, max_tokens=None) -> ChatResult:
        return ChatResult(model_name=model.name, content=self._content,
                          stubbed=self._stubbed)


def test_plan_forces_human_specified_dir(project):
    # LLMが params に危険な dir を書いても、--dir 指定値で必ず上書きされる
    content = ('{"steps": [{"tool": "nachtcode", "action": "read_file",'
               ' "params": {"dir": "/etc", "path": "hello.py"}}]}')
    client = _FakeLLM(content)
    plan = plan_coding_task(
        client, _build_registry(client), str(project), "hello.pyを読んで"
    )
    assert plan.steps[0].params["dir"] == str(project)


def test_plan_rejects_unparseable_output_without_fallback(project):
    client = _FakeLLM("JSONは書けません")
    with pytest.raises(PlanRejected, match="解釈できません"):
        plan_coding_task(
            client, _build_registry(client), str(project), "何かして"
        )
