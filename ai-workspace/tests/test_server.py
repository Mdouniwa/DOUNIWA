"""FastAPI 層の検証（LLM未接続 = stub モードで動く範囲）。"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    for var in ("LOCAL_LLM_BASE_URL", "GITHUB_TOKEN", "OBSIDIAN_VAULT_PATH",
                "N8N_WEBHOOK_BASE_URL", "N8N_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("EXECUTOR_LOG_DIR", str(tmp_path / "logs"))

    # モジュールを再importして、テスト用環境変数で store/orchestrator を作り直す
    import importlib
    import app.server.main as server_main
    importlib.reload(server_main)
    # reload 内の load_dotenv() が実 .env の接続系変数を復活させるため、再度外す
    for var in ("LOCAL_LLM_BASE_URL", "GITHUB_TOKEN", "OBSIDIAN_VAULT_PATH",
                "N8N_WEBHOOK_BASE_URL", "N8N_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return TestClient(server_main.app)


def _wait_done(client: TestClient, run_id: str, timeout_s: float = 30.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError("run が終了しませんでした")


def test_health_and_models(client):
    health = client.get("/api/health").json()
    assert health["llm_up"] is False           # LLM未接続環境
    assert health["endpoint_configured"] is False

    models = client.get("/api/models").json()["models"]
    names = {m["name"] for m in models}
    assert {"qwen-35b", "gemma-31b", "gemma-26b"} <= names


def test_chat_run_and_task_detail_roundtrip(client):
    res = client.post("/api/chat", json={"message": "Obsidianにメモを保存して"})
    assert res.status_code == 200
    run_id = res.json()["run_id"]

    run = _wait_done(client, run_id)
    assert run["status"] in ("done", "failed")
    assert run["record_id"]
    assert "llm_output" in run

    # タスク一覧に反映されている
    tasks = client.get("/api/tasks").json()["tasks"]
    assert any(t["id"] == run["record_id"] for t in tasks)

    # 詳細: step_results（ツール呼び出し詳細）が取れる
    detail = client.get(f"/api/tasks/{run['record_id']}").json()
    assert detail["title"] == "Obsidianにメモを保存して"
    assert detail["steps"], "ツール呼び出しが記録されていること"
    step = detail["steps"][0]
    assert step["tool"] == "obsidian"
    assert step["stubbed"] is True        # vault未設定 → stub が正直に残る
    assert detail["tools"][0]["state"] == "stub"


def test_chat_rejects_empty_and_unknown_model(client):
    assert client.post("/api/chat", json={"message": "  "}).status_code == 400
    assert client.post(
        "/api/chat", json={"message": "hi", "model": "gpt-99"}
    ).status_code == 400


def test_unknown_task_returns_404(client):
    assert client.get("/api/tasks/deadbeef0000").status_code == 404


def test_frontend_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "kuro" in res.text


def test_sessions_isolated_and_deletable(client):
    # 会話A・Bでそれぞれタスクを実行
    res_a = client.post("/api/chat", json={"message": "量子力学を説明して",
                                           "session_id": "sess-a"}).json()
    assert res_a["session_id"] == "sess-a"
    _wait_done(client, res_a["run_id"])
    res_b = client.post("/api/chat", json={"message": "相対性理論を説明して",
                                           "session_id": "sess-b"}).json()
    _wait_done(client, res_b["run_id"])

    # 一覧に両方あり、各会話の履歴は自分のタスクだけを含む
    sessions = client.get("/api/sessions").json()["sessions"]
    assert {s["session_id"] for s in sessions} == {"sess-a", "sess-b"}
    msgs_a = client.get("/api/sessions/sess-a").json()["messages"]
    assert [m["task_text"] for m in msgs_a] == ["量子力学を説明して"]

    # 会話Bを削除しても会話Aは無傷
    deleted = client.delete("/api/sessions/sess-b").json()
    assert deleted["deleted"] == 1
    sessions = client.get("/api/sessions").json()["sessions"]
    assert {s["session_id"] for s in sessions} == {"sess-a"}
    assert client.get("/api/sessions/sess-a").json()["messages"]


def test_nachtcode_rejects_dangerous_and_missing_dirs(client):
    res = client.post("/api/nachtcode", json={"dir": "/etc", "task": "編集して"})
    assert res.status_code == 400
    assert "安全ガード" in res.json()["detail"]

    res = client.post("/api/nachtcode",
                      json={"dir": "/no/such/dir", "task": "編集して"})
    assert res.status_code == 400
    assert "存在しません" in res.json()["detail"]


def test_nachtcode_requires_force_for_non_git_dir(client, tmp_path):
    proj = tmp_path / "plain"
    proj.mkdir()
    res = client.post("/api/nachtcode", json={"dir": str(proj), "task": "何かして"})
    assert res.status_code == 400
    assert "git リポジトリではない" in res.json()["detail"]


def test_nachtcode_run_stops_honestly_when_llm_stubbed(client, tmp_path):
    import subprocess
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)

    res = client.post("/api/nachtcode", json={"dir": str(proj), "task": "xを2にして"})
    assert res.status_code == 200
    run_id = res.json()["run_id"]
    deadline = time.time() + 30
    while time.time() < deadline:
        run = client.get(f"/api/nachtcode/{run_id}").json()
        if run["status"] != "running":
            break
        time.sleep(0.1)
    assert run["status"] == "failed"          # LLM未接続 → 正直に失敗
    assert "stub" in run["error"]
    assert run["record_id"]                    # 記録は残る
    assert run["steps"] == []                  # 何も実行していない
    assert (proj / "a.py").read_text(encoding="utf-8") == "x = 1\n"  # 無傷


def test_chat_without_session_id_issues_new_one(client):
    res = client.post("/api/chat", json={"message": "こんにちは"}).json()
    assert res["session_id"]
    run = _wait_done(client, res["run_id"])
    record = client.get(f"/api/tasks/{run['record_id']}").json()
    assert record["session_id"] == res["session_id"]
