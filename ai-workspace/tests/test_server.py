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


def test_delete_task_removes_single_record(client):
    r1 = client.post("/api/chat", json={"message": "削除対象タスク"}).json()
    _wait_done(client, r1["run_id"])
    r2 = client.post("/api/chat", json={"message": "残すタスク"}).json()
    _wait_done(client, r2["run_id"])

    before = client.get("/api/tasks").json()["tasks"]
    target = next(t for t in before if t["title"] == "削除対象タスク")

    res = client.delete(f"/api/tasks/{target['id']}")
    assert res.status_code == 200
    assert res.json()["deleted"] == 1

    after = client.get("/api/tasks").json()["tasks"]
    assert len(after) == len(before) - 1
    assert all(t["id"] != target["id"] for t in after)
    assert any(t["title"] == "残すタスク" for t in after)  # 他は無傷

    assert client.delete(f"/api/tasks/{target['id']}").status_code == 404


def test_delete_task_rejects_running(client):
    import app.server.main as server_main
    from datetime import datetime
    entry = server_main.RunEntry(
        run_id="fake-run", task_text="実行中タスク", model=None,
        started_at=datetime.now().isoformat(timespec="seconds"),
        record_id="running-rec-01", status="running",
    )
    with server_main._runs_lock:
        server_main._runs[entry.run_id] = entry
    try:
        res = client.delete("/api/tasks/running-rec-01")
        assert res.status_code == 409
        assert "実行中" in res.json()["detail"]
    finally:
        with server_main._runs_lock:
            server_main._runs.pop("fake-run", None)


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


def test_suggest_dirs_filters_missing_and_dangerous(client, tmp_path, monkeypatch):
    import app.server.main as server_main
    ok_dir = tmp_path / "proj"
    ok_dir.mkdir()
    monkeypatch.setattr(server_main, "_SUGGESTED_DIRS", [
        {"path": str(ok_dir), "label": "存在する候補"},
        {"path": str(tmp_path / "missing"), "label": "存在しない候補"},
        {"path": "/etc", "label": "危険な候補"},
    ])
    dirs = client.get("/api/nachtcode/suggest-dirs").json()["dirs"]
    assert [d["label"] for d in dirs] == ["存在する候補"]  # 他2件は除外
    assert dirs[0]["git"] is False


def test_suggest_dirs_route_not_swallowed_by_run_id(client):
    # /api/nachtcode/{run_id} より先に定義されていることの回帰テスト
    res = client.get("/api/nachtcode/suggest-dirs")
    assert res.status_code == 200
    assert "dirs" in res.json()


def test_chat_without_session_id_issues_new_one(client):
    res = client.post("/api/chat", json={"message": "こんにちは"}).json()
    assert res["session_id"]
    run = _wait_done(client, res["run_id"])
    record = client.get(f"/api/tasks/{run['record_id']}").json()
    assert record["session_id"] == res["session_id"]


# --- Nacht Code: 進捗ポーリングと waiting_confirmation -----------------------


def _wait_code_run(client: TestClient, run_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        run = client.get(f"/api/nachtcode/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("nachtcode run が終了しませんでした")


def _git_proj(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".git").mkdir()
    return proj


def _fake_plan(monkeypatch, server_main):
    from app.orchestrator.planner import Plan, PlanStep
    step = PlanStep("browser", "open_page", {"url": "https://example.com"})
    monkeypatch.setattr(
        server_main, "plan_coding_task",
        lambda *a, **k: Plan(steps=(step,), source="llm"),
    )


def test_nachtcode_needs_confirmation_ends_as_waiting_confirmation(
    client, tmp_path, monkeypatch
):
    import app.server.main as server_main
    from app.orchestrator.executor import StepResult

    _fake_plan(monkeypatch, server_main)

    def fake_execute_plan(plan, registry, task_text, on_step=None, **kw):
        r = StepResult(
            index=1, tool="browser", action="open_page", params={},
            ok=True, output="ドメイン承認待ち",
            data={"needs_confirmation": True, "kind": "domain",
                  "domain": "example.com", "url": "https://example.com"},
        )
        if on_step:
            on_step(r)
        return [r]

    monkeypatch.setattr(server_main, "execute_plan", fake_execute_plan)

    res = client.post("/api/nachtcode",
                      json={"dir": str(_git_proj(tmp_path)), "task": "見て"})
    assert res.status_code == 200
    run = _wait_code_run(client, res.json()["run_id"])
    assert run["status"] == "waiting_confirmation"  # failed にしない
    assert run["steps"][0]["data"]["needs_confirmation"] is True
    assert run["plan"] and run["plan"][0]["tool"] == "browser"

    # TASKS 画面が受け取る status はフロント（kuro.js statusText）が
    # 表示できる既知の値のみ。承認待ち record は「失敗」に畳まれない。
    tasks = client.get("/api/tasks").json()["tasks"]
    statuses = {t["status"] for t in tasks}
    assert statuses <= {"running", "done", "failed", "waiting_confirmation"}
    parent = next(t for t in tasks if t["tag"] == "coding")
    assert parent["status"] == "waiting_confirmation"


def test_nachtcode_exposes_live_steps_while_running(client, tmp_path, monkeypatch):
    import threading

    import app.server.main as server_main
    from app.orchestrator.executor import StepResult

    _fake_plan(monkeypatch, server_main)
    first_step_done = threading.Event()
    release = threading.Event()

    def fake_execute_plan(plan, registry, task_text, on_step=None, **kw):
        r1 = StepResult(index=1, tool="browser", action="open_page",
                        params={}, ok=True, output="1つ目完了", data={})
        on_step(r1)
        first_step_done.set()
        release.wait(timeout=10)
        r2 = StepResult(index=2, tool="browser", action="read_text",
                        params={}, ok=True, output="2つ目完了", data={})
        on_step(r2)
        return [r1, r2]

    monkeypatch.setattr(server_main, "execute_plan", fake_execute_plan)

    res = client.post("/api/nachtcode",
                      json={"dir": str(_git_proj(tmp_path)), "task": "見て"})
    run_id = res.json()["run_id"]
    assert first_step_done.wait(timeout=10)

    # 実行中でも確定済みステップと計画が見える（ポーリング先の応答）
    mid = client.get(f"/api/nachtcode/{run_id}").json()
    assert mid["status"] == "running"
    assert len(mid["steps"]) == 1
    assert mid["steps"][0]["output"] == "1つ目完了"
    assert mid["plan"]

    release.set()
    run = _wait_code_run(client, run_id)
    assert run["status"] == "done"
    assert len(run["steps"]) == 2


# --- 承認後の実行結果の run 反映と追記レコード（案B） -------------------------


class _FakeBrowserAdapter:
    """承認POSTの先で実行される BrowserAdapter の置き換え（実ネットワークなし）。"""

    supported_actions = ("fetch_page",)
    result = None  # テスト側で ToolResult を差し込む

    def execute(self, request):
        return type(self).result


def _waiting_run(client, tmp_path, monkeypatch):
    """needs_confirmation で停止した run を作り run_id を返す。"""
    import app.server.main as server_main
    from app.orchestrator.executor import StepResult

    _fake_plan(monkeypatch, server_main)

    def fake_execute_plan(plan, registry, task_text, on_step=None, **kw):
        r = StepResult(
            index=1, tool="browser", action="fetch_page", params={},
            ok=True, output="[確認待ち] まだアクセスしていません",
            data={"needs_confirmation": True, "kind": "domain",
                  "domain": "example.com", "url": "https://example.com",
                  "params": {"url": "https://example.com"}},
        )
        if on_step:
            on_step(r)
        return [r]

    monkeypatch.setattr(server_main, "execute_plan", fake_execute_plan)
    res = client.post("/api/nachtcode",
                      json={"dir": str(_git_proj(tmp_path)), "task": "取得して"})
    run = _wait_code_run(client, res.json()["run_id"])
    assert run["status"] == "waiting_confirmation"
    return run


def _patch_browser_adapter(monkeypatch, result):
    import app.tools.browser.adapter as browser_adapter
    _FakeBrowserAdapter.result = result
    monkeypatch.setattr(browser_adapter, "BrowserAdapter", _FakeBrowserAdapter)


def test_confirm_with_run_id_updates_entry_and_appends_record(
    client, tmp_path, monkeypatch
):
    from app.tools.base import ToolResult

    run = _waiting_run(client, tmp_path, monkeypatch)
    parent_record_id = run["record_id"]
    _patch_browser_adapter(monkeypatch, ToolResult(
        ok=True,
        output="[外部データ開始] Example Domain [外部データ終了]",
        data={"url": "https://example.com", "title": "Example Domain"},
    ))

    res = client.post("/api/browser/confirm", json={
        "kind": "domain", "action": "fetch_page",
        "params": {"url": "https://example.com"},
        "run_id": run["run_id"], "step_index": 1,
    })
    assert res.status_code == 200 and res.json()["ok"] is True

    # entry.steps が実行結果へ差し替わり、run は done へ遷移する
    after = client.get(f"/api/nachtcode/{run['run_id']}").json()
    assert after["status"] == "done"
    assert "外部データ開始" in after["steps"][0]["output"]
    assert not (after["steps"][0]["data"] or {}).get("needs_confirmation")

    # 承認後の実行が新規レコードとして追記される（元recordは書き換えない）
    tasks = client.get("/api/tasks").json()["tasks"]
    confirm_rec = next(t for t in tasks if t["tag"] == "browser_confirm")
    assert confirm_rec["status"] == "done"
    parent = client.get(f"/api/tasks/{parent_record_id}").json()
    assert parent["steps"][0]["data"]["needs_confirmation"] is True  # 承認前のまま
    assert parent["status"] == "waiting_confirmation"

    detail = client.get(f"/api/tasks/{confirm_rec['id']}").json()
    assert "外部データ開始" in detail["steps"][0]["output"]
    assert parent_record_id in detail["route_reason"]  # 親レコードへの参照


def test_confirm_multi_stage_keeps_waiting_and_no_record(
    client, tmp_path, monkeypatch
):
    from app.tools.base import ToolResult

    run = _waiting_run(client, tmp_path, monkeypatch)
    _patch_browser_adapter(monkeypatch, ToolResult(
        ok=True, output="[確認待ち] 送信の最終確認",
        data={"needs_confirmation": True, "kind": "write", "final": True,
              "confirm_token": "tok2", "params": {}},
    ))

    res = client.post("/api/browser/confirm", json={
        "kind": "domain", "action": "fetch_page",
        "params": {"url": "https://example.com"},
        "run_id": run["run_id"], "step_index": 1,
    })
    assert res.status_code == 200

    after = client.get(f"/api/nachtcode/{run['run_id']}").json()
    assert after["status"] == "waiting_confirmation"  # 多段承認の途中は維持
    tags = [t["tag"] for t in client.get("/api/tasks").json()["tasks"]]
    assert "browser_confirm" not in tags  # 実行が確定するまで追記しない


def test_confirm_without_run_id_is_backward_compatible(
    client, tmp_path, monkeypatch
):
    from app.tools.base import ToolResult

    run = _waiting_run(client, tmp_path, monkeypatch)
    _patch_browser_adapter(monkeypatch, ToolResult(
        ok=True, output="完了", data={},
    ))

    res = client.post("/api/browser/confirm", json={
        "kind": "domain", "action": "fetch_page",
        "params": {"url": "https://example.com"},
    })
    assert res.status_code == 200 and res.json()["ok"] is True

    after = client.get(f"/api/nachtcode/{run['run_id']}").json()
    assert after["status"] == "waiting_confirmation"  # run には触れない
    tags = [t["tag"] for t in client.get("/api/tasks").json()["tasks"]]
    assert "browser_confirm" not in tags
