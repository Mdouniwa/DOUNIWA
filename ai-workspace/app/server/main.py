"""kuro·console — Web API + フロントエンド配信。

既存の Orchestrator を薄くラップする FastAPI 層:
  - POST /api/chat      : タスクをバックグラウンドスレッドで実行し run_id を即返す
  - GET  /api/runs/{id} : 実行中タスクの状態（UIが数秒間隔でポーリングする。WSは使わない）
  - GET  /api/tasks     : 実行中 + MemoryStore.load_recent() のタスク一覧
  - GET  /api/tasks/{id}: 1タスクの詳細（step_results = ツール呼び出し詳細を含む）
  - GET  /api/models    : モデル一覧（UIのモデル選択ピル用）
  - GET  /api/health    : ローカルLLM疎通と実行中件数
  - /                   : web/ 配下の静的フロントエンド（kuro·console UI）

信頼性の原則はUIにも引き継ぐ: ステップの成功/失敗/stub/スキップは
step_results の事実をそのまま返し、サーバー側で作文しない。
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()  # uvicorn 直起動でも .env を読む

from app.llm.models import DEFAULT_MODEL, get_model, list_models  # noqa: E402
from app.memory.store import MemoryStore  # noqa: E402
from app.orchestrator.core import Orchestrator  # noqa: E402

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parents[2] / "web"

# UI 表示用のモデルラベル
_MODEL_LABELS = {
    "qwen-35b": "Qwen 35B",
    "gemma-31b": "Gemma 31B",
    "gemma-26b": "Gemma 26B",
    "llama-70b": "Llama 70B",
    "cloud-claude": "Claude",
    "cloud-gemini": "Gemini",
}


@dataclass
class RunEntry:
    """実行中（またはスレッド完了直後）のタスク。"""

    run_id: str
    task_text: str
    model: str | None
    started_at: str
    session_id: str = ""
    status: str = "running"          # running | done | failed
    record_id: str | None = None
    error: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class ChatRequest(BaseModel):
    message: str
    model: str | None = None       # 内部モデル名（qwen-35b 等）。None = 自動選択
    session_id: str | None = None  # 会話ID。None なら新規発行して返す


app = FastAPI(title="kuro-console", docs_url=None, redoc_url=None)

_store = MemoryStore()
_orchestrator = Orchestrator(store=_store)
_runs: dict[str, RunEntry] = {}
_runs_lock = threading.Lock()


def _execute_run(entry: RunEntry) -> None:
    try:
        outcome = _orchestrator.run(
            entry.task_text,
            explicit_model=entry.model,
            session_id=entry.session_id or None,
        )
        with entry.lock:
            entry.record_id = outcome.record_id
            entry.status = "failed" if outcome.tool_ok is False else "done"
    except Exception as exc:  # 実行スレッドを静かに死なせない
        logger.exception("run %s failed", entry.run_id)
        with entry.lock:
            entry.status = "failed"
            entry.error = str(exc)


@app.post("/api/chat")
def post_chat(req: ChatRequest) -> dict:
    text = req.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message が空です")
    if req.model:
        try:
            get_model(req.model)
        except KeyError:
            raise HTTPException(status_code=400, detail=f"未知のモデル: {req.model}")
    session_id = (req.session_id or "").strip() or uuid.uuid4().hex[:12]
    entry = RunEntry(
        run_id=uuid.uuid4().hex[:12],
        task_text=text,
        model=req.model or None,
        started_at=datetime.now().isoformat(timespec="seconds"),
        session_id=session_id,
    )
    with _runs_lock:
        _runs[entry.run_id] = entry
    threading.Thread(target=_execute_run, args=(entry,), daemon=True).start()
    return {"run_id": entry.run_id, "status": "running", "session_id": session_id}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    with _runs_lock:
        entry = _runs.get(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="run が見つかりません")
    with entry.lock:
        result = {
            "run_id": entry.run_id,
            "status": entry.status,
            "record_id": entry.record_id,
            "error": entry.error,
            "task_text": entry.task_text,
            "started_at": entry.started_at,
        }
    if result["record_id"]:
        record = _store.load_by_id(result["record_id"])
        if record:
            result["record"] = _task_summary(record)
            result["llm_output"] = record.get("llm_output", "")
            result["model_name"] = record.get("model_name", "")
            result["stubbed"] = record.get("stubbed", False)
    return result


def _step_state(step: dict) -> str:
    if step.get("skipped"):
        return "skip"
    if step.get("stubbed"):
        return "stub"
    return "done" if step.get("ok") else "failed"


def _hhmm(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%H:%M")
    except ValueError:
        return "--:--"


def _synth_log(record: dict) -> str:
    """step_results から事実ベースの実行ログを合成する（作文はしない）。"""
    lines = []
    for s in record.get("step_results", []):
        t = s.get("started_at", "")
        clock = t[11:19] if len(t) >= 19 else "--:--:--"
        label = f"{s.get('tool')}.{s.get('action')}"
        if s.get("skipped"):
            status = f"スキップ: {s.get('skip_reason', '')}"
        elif s.get("stubbed"):
            status = "stub（未実行）"
        elif s.get("ok"):
            status = f"成功 ({s.get('duration_s', 0):.1f}s)"
        else:
            status = f"失敗 ({s.get('duration_s', 0):.1f}s)"
        lines.append(f"{clock}  {label:<22} -> {status}")
    return "\n".join(lines)


def _task_summary(record: dict) -> dict:
    steps = record.get("step_results", [])
    tool_ok = record.get("tool_ok")
    status = "failed" if tool_ok is False else "done"
    return {
        "id": record.get("id"),
        "run_id": None,
        "status": status,
        "session_id": record.get("session_id", ""),
        "title": record.get("task_text", ""),
        "time": _hhmm(record.get("timestamp", "")),
        "duration_s": round(sum(s.get("duration_s", 0) for s in steps), 1),
        "model": record.get("model_name", ""),
        "model_label": _MODEL_LABELS.get(record.get("model_name", ""),
                                         record.get("model_name", "")),
        "tag": record.get("task_kind", ""),
        "plan_source": record.get("plan_source", ""),
        "plan_note": record.get("plan_note", ""),
        "stubbed": record.get("stubbed", False),
        "tools": [
            {
                "index": s.get("index"),
                "tool": s.get("tool"),
                "action": s.get("action"),
                "state": _step_state(s),
            }
            for s in steps
        ],
        "log": _synth_log(record),
    }


@app.get("/api/tasks")
def get_tasks(limit: int = 20) -> dict:
    with _runs_lock:
        entries = sorted(_runs.values(), key=lambda e: e.started_at, reverse=True)
    running = []
    for e in entries:
        with e.lock:
            if e.status != "running":
                continue
            running.append({
                "id": None,
                "run_id": e.run_id,
                "status": "running",
                "title": e.task_text,
                "time": _hhmm(e.started_at),
                "started_at": e.started_at,
                "duration_s": None,
                "model": e.model or "auto",
                "model_label": _MODEL_LABELS.get(e.model or "", e.model or "自動選択"),
                "tag": "…",
                "plan_source": "",
                "plan_note": "",
                "stubbed": False,
                "tools": [],
                "log": "",
            })
    records = [
        _task_summary(r)
        for r in reversed(_store.load_recent(limit, any_session=True))
    ]
    return {"tasks": running + records}


@app.get("/api/tasks/{record_id}")
def get_task(record_id: str) -> dict:
    record = _store.load_by_id(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="タスクが見つかりません")
    summary = _task_summary(record)
    summary["llm_output"] = record.get("llm_output", "")
    summary["timestamp"] = record.get("timestamp", "")
    summary["route_reason"] = record.get("route_reason", "")
    summary["plan"] = record.get("plan", [])
    summary["steps"] = record.get("step_results", [])
    return summary


@app.get("/api/sessions")
def get_sessions() -> dict:
    return {"sessions": _store.list_sessions()}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    records = _store.load_session(session_id)
    return {
        "session_id": session_id,
        "messages": [
            {
                "id": r.get("id"),
                "task_text": r.get("task_text", ""),
                "llm_output": r.get("llm_output", ""),
                "model": r.get("model_name", ""),
                "time": _hhmm(r.get("timestamp", "")),
                "stubbed": r.get("stubbed", False),
            }
            for r in records
        ],
    }


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict:
    with _runs_lock:
        active = any(
            e.session_id == session_id and e.status == "running"
            for e in _runs.values()
        )
    if active:
        raise HTTPException(
            status_code=409, detail="この会話は実行中のタスクがあるため削除できません"
        )
    deleted = _store.delete_session(session_id)
    return {"session_id": session_id, "deleted": deleted}


@app.get("/api/models")
def get_models() -> dict:
    models = []
    for spec in list_models():
        models.append({
            "name": spec.name,
            "label": _MODEL_LABELS.get(spec.name, spec.name),
            "tier": spec.tier.value,
            "configured": spec.resolve_endpoint() is not None,
            "default": spec.name == DEFAULT_MODEL,
        })
    return {"models": models}


# LLM疎通の判定は「実際に使うモデルへの最小 completion」で行う。
# （プロキシの GET /models は停止中バックエンドへ飛び 502 になり得るため、
#   実際の使用可否を反映しない。）結果は60秒キャッシュし、UIの数秒間隔の
# ポーリングで推論リクエストが増えないようにする。
_HEALTH_TTL_S = 60.0
_health_cache = {"checked_at": 0.0, "llm_up": False}
_health_lock = threading.Lock()


def _probe_llm() -> bool:
    base = os.environ.get("LOCAL_LLM_BASE_URL")
    if not base:
        return False
    try:
        spec = get_model(DEFAULT_MODEL)
        resp = httpx.post(
            base.rstrip("/") + "/chat/completions",
            json={
                "model": spec.served_model_name,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=5.0,
        )
        return resp.status_code == 200
    except (httpx.HTTPError, KeyError):
        return False


@app.get("/api/health")
def get_health() -> dict:
    import time
    with _health_lock:
        if time.monotonic() - _health_cache["checked_at"] > _HEALTH_TTL_S:
            _health_cache["llm_up"] = _probe_llm()
            _health_cache["checked_at"] = time.monotonic()
        llm_up = _health_cache["llm_up"]
    with _runs_lock:
        running = sum(1 for e in _runs.values() if e.status == "running")
    return {
        "llm_up": llm_up,
        "endpoint_configured": bool(os.environ.get("LOCAL_LLM_BASE_URL")),
        "default_model": DEFAULT_MODEL,
        "running": running,
    }


# 静的フロントエンド（API ルート定義の後にマウントする）
if _WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
