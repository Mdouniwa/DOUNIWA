"""MemoryStore のセッション操作（一覧・絞り込み・削除）の検証。"""

from __future__ import annotations

import json

from app.memory.store import MemoryStore, TaskRecord


def _seed(store: MemoryStore, task_text: str, session_id: str = "") -> None:
    store.save(TaskRecord(
        task_text=task_text, task_kind="general", model_name="qwen-35b",
        route_reason="test", tool_name=None, tool_action=None,
        tool_output="", llm_output=f"{task_text} の結果", stubbed=False,
        session_id=session_id,
    ))


def test_load_recent_filters_by_session(tmp_path):
    store = MemoryStore(base_dir=tmp_path)
    _seed(store, "レガシー1")                      # session なし
    _seed(store, "A1", session_id="sess-a")
    _seed(store, "B1", session_id="sess-b")
    _seed(store, "A2", session_id="sess-a")

    assert [r["task_text"] for r in store.load_recent(5)] == ["レガシー1"]
    assert [r["task_text"] for r in store.load_recent(5, session_id="sess-a")] \
        == ["A1", "A2"]
    assert [r["task_text"] for r in store.load_recent(5, session_id="sess-b")] \
        == ["B1"]


def test_list_sessions_excludes_legacy(tmp_path):
    store = MemoryStore(base_dir=tmp_path)
    _seed(store, "レガシー1")
    _seed(store, "A1", session_id="sess-a")
    _seed(store, "A2", session_id="sess-a")
    _seed(store, "B1", session_id="sess-b")

    sessions = store.list_sessions()
    assert {s["session_id"] for s in sessions} == {"sess-a", "sess-b"}
    a = next(s for s in sessions if s["session_id"] == "sess-a")
    assert a["count"] == 2
    assert a["title"] == "A1"  # 最初のタスクがタイトル


def test_delete_session_leaves_others_untouched(tmp_path):
    store = MemoryStore(base_dir=tmp_path)
    _seed(store, "レガシー1")
    _seed(store, "A1", session_id="sess-a")
    _seed(store, "B1", session_id="sess-b")
    _seed(store, "A2", session_id="sess-a")

    deleted = store.delete_session("sess-a")
    assert deleted == 2

    remaining = [json.loads(l) for f in sorted(tmp_path.glob("runs-*.jsonl"))
                 for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    texts = [r["task_text"] for r in remaining]
    assert texts == ["レガシー1", "B1"]  # レガシーと他会話は無傷


def test_delete_session_refuses_empty_id(tmp_path):
    """空IDでの削除は拒否（レガシー記録の一括削除を防ぐ安全弁）。"""
    store = MemoryStore(base_dir=tmp_path)
    _seed(store, "レガシー1")
    assert store.delete_session("") == 0
    assert len(store.load_recent(5)) == 1


def test_load_session_returns_records_in_order(tmp_path):
    store = MemoryStore(base_dir=tmp_path)
    _seed(store, "A1", session_id="sess-a")
    _seed(store, "B1", session_id="sess-b")
    _seed(store, "A2", session_id="sess-a")
    assert [r["task_text"] for r in store.load_session("sess-a")] == ["A1", "A2"]
    assert store.load_session("") == []
