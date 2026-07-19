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


def test_save_note_title_extracted_from_quoted_task_text(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_NOTE_FOLDER", "00_Inbox_personal")

    request = ToolRequest(
        action="save_note",
        params={},
        task_text="Obsidianに『2回目の実装テスト:バグ修正確認』というメモを保存して",
    )
    result = ObsidianAdapter().execute(request)

    assert result.ok is True
    files = list((tmp_path / "00_Inbox_personal").glob("*.md"))
    assert len(files) == 1
    # 半角コロンはファイル名では除去され、frontmatter には残る
    assert "2回目の実装テストバグ修正確認" in files[0].name
    assert 'title: "2回目の実装テスト:バグ修正確認"' in files[0].read_text(encoding="utf-8")


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


# ----------------------------------------------------------------------
# vault 切り替え（personal / akane）
# ----------------------------------------------------------------------

def _setup_vaults(tmp_path, monkeypatch):
    personal = tmp_path / "personal"
    akane = tmp_path / "akane"
    personal.mkdir()
    akane.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(personal))
    monkeypatch.setenv("OBSIDIAN_NOTE_FOLDER", "00_Inbox_personal")
    monkeypatch.setenv("OBSIDIAN_VAULT_AKANE_PATH", str(akane))
    monkeypatch.setenv("OBSIDIAN_NOTE_FOLDER_AKANE", "00_Inbox_akane")
    return personal, akane


def test_save_note_vault_param_selects_akane(tmp_path, monkeypatch):
    _, akane = _setup_vaults(tmp_path, monkeypatch)
    request = ToolRequest(
        action="save_note",
        params={"title": "あかね側テスト", "body": "本文", "vault": "akane"},
        task_text="メモを保存して",
    )
    result = ObsidianAdapter().execute(request)
    assert result.ok is True
    assert result.data["vault"] == "akane"
    assert len(list((akane / "00_Inbox_akane").glob("*.md"))) == 1


def test_save_note_task_text_akane_selects_akane_vault(tmp_path, monkeypatch):
    personal, akane = _setup_vaults(tmp_path, monkeypatch)
    request = ToolRequest(
        action="save_note",
        params={"title": "T", "body": "B"},
        task_text="あかねのObsidianにメモを保存して",
    )
    result = ObsidianAdapter().execute(request)
    assert result.ok is True
    assert len(list((akane / "00_Inbox_akane").glob("*.md"))) == 1
    assert list(personal.rglob("*.md")) == []


def test_akane_vault_unset_returns_stub(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.delenv("OBSIDIAN_VAULT_AKANE_PATH", raising=False)
    request = ToolRequest(
        action="save_note",
        params={"title": "T", "vault": "akane"},
        task_text="メモを保存して",
    )
    result = ObsidianAdapter().execute(request)
    assert result.stubbed is True
    assert "実際には実行されていません" in result.output


# ----------------------------------------------------------------------
# search_notes
# ----------------------------------------------------------------------

def test_search_notes_finds_matches_with_snippet(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "buy.md").write_text(
        "# 買い物\n\n牛乳を買う\n", encoding="utf-8"
    )
    (tmp_path / "other.md").write_text("無関係\n", encoding="utf-8")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "config.md").write_text("牛乳", encoding="utf-8")

    result = ObsidianAdapter().execute(ToolRequest(
        action="search_notes", params={"query": "牛乳"}, task_text="検索して",
    ))
    assert result.ok is True
    assert len(result.data["matches"]) == 1  # .obsidian 配下は対象外
    assert result.data["matches"][0]["path"] == "notes/buy.md"
    assert "牛乳を買う" in result.output


def test_search_notes_no_match_is_honest(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    result = ObsidianAdapter().execute(ToolRequest(
        action="search_notes", params={"query": "存在しない語"}, task_text="",
    ))
    assert result.ok is True
    assert "見つかりませんでした" in result.output


def test_search_notes_requires_query(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    result = ObsidianAdapter().execute(ToolRequest(
        action="search_notes", params={}, task_text="検索して",
    ))
    assert result.ok is False


# ----------------------------------------------------------------------
# append_note
# ----------------------------------------------------------------------

def test_append_note_appends_to_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    note = tmp_path / "既存ノート.md"
    note.write_text("# 既存\n元の本文\n", encoding="utf-8")

    result = ObsidianAdapter().execute(ToolRequest(
        action="append_note",
        params={"path": "既存ノート", "body": "追記された行"},
        task_text="追記して",
    ))
    assert result.ok is True
    text = note.read_text(encoding="utf-8")
    assert text.startswith("# 既存\n元の本文\n")  # 元の内容は無傷
    assert "追記された行" in text


def test_append_note_refuses_to_create_missing_note(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    result = ObsidianAdapter().execute(ToolRequest(
        action="append_note",
        params={"path": "存在しないノート", "body": "本文"},
        task_text="追記して",
    ))
    assert result.ok is False
    assert "追記できません" in result.output
    assert list(tmp_path.rglob("*.md")) == []  # 何も作られていない


def test_append_note_rejects_ambiguous_target(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    (tmp_path / "会議メモ1.md").write_text("a", encoding="utf-8")
    (tmp_path / "会議メモ2.md").write_text("b", encoding="utf-8")
    result = ObsidianAdapter().execute(ToolRequest(
        action="append_note",
        params={"path": "会議メモ", "body": "本文"},
        task_text="追記して",
    ))
    assert result.ok is False
    assert "特定できません" in result.output


def test_append_note_rejects_path_outside_vault(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("外部ファイル", encoding="utf-8")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    result = ObsidianAdapter().execute(ToolRequest(
        action="append_note",
        params={"path": "../outside.md", "body": "本文"},
        task_text="追記して",
    ))
    assert result.ok is False
    assert outside.read_text(encoding="utf-8") == "外部ファイル"  # 無傷
