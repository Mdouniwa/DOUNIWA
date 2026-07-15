"""ObsidianAdapter の実書き込み動作の検証（tmp_path を vault に見立てる）。"""

from __future__ import annotations

from datetime import datetime

from app.tools.base import ToolRequest
from app.tools.obsidian.adapter import ObsidianAdapter


def _request(title: str = "実装テスト", body: str = "本文です") -> ToolRequest:
    return ToolRequest(
        action="save_note",
        params={"title": title, "body": body},
        task_text="Obsidianにメモを保存して",
    )


def test_save_note_stub_when_vault_unset(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    result = ObsidianAdapter().execute(_request())
    assert result.ok is True
    assert result.stubbed is True


def test_save_note_writes_file_with_frontmatter(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_NOTE_FOLDER", "00_Inbox_personal")

    result = ObsidianAdapter().execute(_request())

    assert result.ok is True
    assert result.stubbed is False
    files = list((tmp_path / "00_Inbox_personal").glob("*.md"))
    assert len(files) == 1
    assert files[0].name == f"{datetime.now():%Y-%m-%d}_claude_実装テスト.md"
    text = files[0].read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "source: ai-workspace" in text
    assert "本文です" in text


def test_save_note_does_not_overwrite_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_NOTE_FOLDER", "00_Inbox_personal")

    adapter = ObsidianAdapter()
    adapter.execute(_request(body="1回目"))
    adapter.execute(_request(body="2回目"))

    files = sorted((tmp_path / "00_Inbox_personal").glob("*.md"))
    assert len(files) == 2
    assert "1回目" in files[0].read_text(encoding="utf-8")
    assert "2回目" in files[1].read_text(encoding="utf-8")
