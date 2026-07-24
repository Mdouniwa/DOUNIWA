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

from dataclasses import asdict  # noqa: E402

from app.llm.client import LLMClient  # noqa: E402
from app.llm.models import DEFAULT_MODEL, get_model, list_models  # noqa: E402
from app.memory.store import MemoryStore, TaskRecord  # noqa: E402
from app.orchestrator.core import Orchestrator  # noqa: E402
from app.orchestrator.executor import execute_plan  # noqa: E402
from app.orchestrator.planner import PlanRejected  # noqa: E402
from app.tools.nachtcode.adapter import validate_project_dir  # noqa: E402
from app.tools.nachtcode.runner import _build_registry, plan_coding_task  # noqa: E402

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
    if record.get("waiting_confirmation"):
        status = "waiting_confirmation"  # 承認待ち停止を「失敗」に畳まない
    else:
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


@dataclass
class CodeRunEntry:
    """Nacht Code（CODE画面）の実行中/完了タスク。

    plan / steps は実行中の途中経過（UIポーリング用）。ステップが確定する
    たびに追記され、完了後は保存済みレコードと同内容になる。
    """

    run_id: str
    target_dir: str
    task_text: str
    started_at: str
    status: str = "running"  # running | done | failed | waiting_confirmation
    error: str = ""
    record_id: str | None = None
    plan: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class NachtCodeRequest(BaseModel):
    dir: str
    task: str
    force: bool = False   # git管理外ディレクトリでも実行（バックアップ確認済みの明示）
    model: str | None = None


_code_runs: dict[str, CodeRunEntry] = {}
_code_runs_lock = threading.Lock()
_code_client = LLMClient()


def _execute_code_run(entry: CodeRunEntry, model: str | None) -> None:
    registry = _build_registry(_code_client)
    plan = None
    results = []
    error = ""

    def _on_step(r) -> None:
        # 途中経過をUIポーリングへ公開する（描画はフロント側の責務）
        with entry.lock:
            entry.steps.append(asdict(r))

    try:
        plan = plan_coding_task(
            _code_client, registry, entry.target_dir, entry.task_text, model
        )
        with entry.lock:
            entry.plan = [{"tool": s.tool, "action": s.action, "params": s.params}
                          for s in plan.steps]
        results = execute_plan(plan, registry, entry.task_text, on_step=_on_step)
    except PlanRejected as exc:
        error = str(exc)
    except Exception as exc:  # 実行スレッドを静かに死なせない
        logger.exception("nachtcode run %s failed", entry.run_id)
        error = f"予期しないエラー: {exc}"

    executed = [r for r in results if not r.skipped]
    ok = bool(executed) and all(r.ok for r in executed) \
        and not any(r.skipped for r in results)
    # 承認待ちで停止した run は成功/失敗の2値に畳まず、その事実を記録する
    # （人間の承認チャネルの操作待ち。承認後の実行は別レコードとして追記）。
    waiting = not error and any(
        (r.data or {}).get("needs_confirmation")
        for r in results if not r.skipped
    )
    if error:
        summary = f"Nacht Code: 実行しませんでした。{error}"
    elif waiting:
        summary = (
            "Nacht Code: 承認待ちで停止しました（未承認のステップは実行して"
            f"いません。承認は画面の確認パネルから。対象: {entry.target_dir}）"
        )
    else:
        summary = (
            f"Nacht Code 実行結果: 成功{sum(1 for r in executed if r.ok)}"
            f" / 失敗{sum(1 for r in executed if not r.ok)}"
            f" / スキップ{sum(1 for r in results if r.skipped)}"
            f"（対象: {entry.target_dir}）"
        )
    record = TaskRecord(
        task_text=entry.task_text,
        session_id="",
        task_kind="coding",
        model_name=model or DEFAULT_MODEL,
        route_reason="Nacht Code（CODE画面）",
        tool_name="nachtcode",
        tool_action=plan.steps[0].action if plan and plan.steps else None,
        tool_ok=None if error else ok,
        tool_output=executed[-1].output if executed else "",
        llm_output=summary,
        stubbed=any(r.stubbed for r in results),
        plan_source="llm" if plan else "rejected",
        plan_note=error,
        plan=[{"tool": s.tool, "action": s.action, "params": s.params}
              for s in (plan.steps if plan else [])],
        step_results=[asdict(r) for r in results],
        waiting_confirmation=waiting,
    )
    _store.save(record)
    # 承認待ちで停止した run は failed ではなく waiting_confirmation にする
    # （人間の承認チャネルの操作待ち。UIポーリングはここで停止する）。
    with entry.lock:
        entry.record_id = record.id
        if waiting:
            entry.status = "waiting_confirmation"
        else:
            entry.status = "failed" if (error or not ok) else "done"
        entry.error = error


@app.post("/api/nachtcode")
def post_nachtcode(req: NachtCodeRequest) -> dict:
    task = req.task.strip()
    if not task:
        raise HTTPException(status_code=400, detail="タスクが空です")
    root, error = validate_project_dir(req.dir)
    if error:
        raise HTTPException(status_code=400, detail=error)
    if not (root / ".git").exists() and not req.force:
        raise HTTPException(
            status_code=400,
            detail=(
                "対象が git リポジトリではないため、変更の巻き戻し手段がありません。"
                "バックアップを確認のうえ「git管理外でも実行」を有効にしてください。"
            ),
        )
    if req.model:
        try:
            get_model(req.model)
        except KeyError:
            raise HTTPException(status_code=400, detail=f"未知のモデル: {req.model}")
    entry = CodeRunEntry(
        run_id=uuid.uuid4().hex[:12],
        target_dir=str(root),
        task_text=task,
        started_at=datetime.now().isoformat(timespec="seconds"),
    )
    with _code_runs_lock:
        _code_runs[entry.run_id] = entry
    threading.Thread(
        target=_execute_code_run, args=(entry, req.model), daemon=True
    ).start()
    return {"run_id": entry.run_id, "status": "running", "dir": str(root)}


# CODE画面のディレクトリ候補（定義は adapter 側と共有。固定2件のみ）
from app.tools.nachtcode.adapter import SUGGESTED_DIRS as _SUGGESTED_DIRS  # noqa: E402


@app.get("/api/nachtcode/suggest-dirs")
def get_suggest_dirs() -> dict:
    """候補ディレクトリを返す。存在確認と安全ガードを通過したものだけ。

    注意: このルートは /api/nachtcode/{run_id} より先に定義すること
    （後だと "suggest-dirs" が run_id として解釈される）。
    """
    dirs = []
    for candidate in _SUGGESTED_DIRS:
        resolved, error = validate_project_dir(candidate["path"])
        if error:
            logger.info(
                "候補ディレクトリを除外: %s（%s）", candidate["path"], error
            )
            continue
        dirs.append({
            "path": str(resolved),
            "label": candidate["label"],
            "git": (resolved / ".git").exists(),
        })
    return {"dirs": dirs}


class PushRequest(BaseModel):
    dir: str
    remote: str = "origin"
    branch: str | None = None
    confirm: bool = False  # UIの確認ダイアログを通過した場合のみ True


@app.post("/api/nachtcode/push")
def post_nachtcode_push(req: PushRequest) -> dict:
    """git push。confirm=False ならプレビューのみ、True なら実行する。

    confirm=True は UI の確認ダイアログ（人間の明示操作）だけが送る。
    無人の自動 push は行わない。
    """
    from app.tools.base import ToolRequest
    from app.tools.nachtcode.adapter import NachtCodeAdapter

    root, error = validate_project_dir(req.dir)
    if error:
        raise HTTPException(status_code=400, detail=error)
    params = {"dir": str(root), "remote": req.remote}
    if req.branch:
        params["branch"] = req.branch
    if req.confirm:
        params["confirmed"] = True
    result = NachtCodeAdapter().execute(
        ToolRequest(action="git_push", params=params, task_text="UIからのpush")
    )
    return {"ok": result.ok, "output": result.output, "data": result.data}


class BrowserConfirmRequest(BaseModel):
    """browser の人間承認チャネル（UI）からの確認POST。

    kind="domain": ドメイン承認。persist=True（恒久ボタン）のときだけ
    allowlist へ恒久追記する。kind="write": write承認。confirm_token は
    プレビュー時に adapter が発行したワンタイムトークン。
    """

    kind: str                        # "domain" | "write"
    action: str                      # browser の action 名
    params: dict = {}                # プレビュー時と同じ params
    persist: bool = False            # domain: 恒久追記（UIの恒久ボタンのみ True）
    confirm_token: str | None = None  # write: ワンタイムトークン
    # 承認結果を元の run/record に紐付けるための識別子（UIは渡すだけ）。
    # 無し/不一致でも承認自体は従来通り動く（後方互換）。
    run_id: str | None = None
    step_index: int | None = None


def _record_confirm_result(req: BrowserConfirmRequest, result) -> None:
    """承認後の実行結果を元の run（in-memory）と記録（追記）に反映する。

    - 次の needs_confirmation が返っている間（多段承認の途中）は何もしない。
    - entry の更新は waiting_confirmation の run に限る（実行中の run の
      ステータスを承認チャネルから動かさない）。
    - record は書き換えず、承認後の実行を新規レコードとして追記する
    　（MemoryStore の追記専用原則。元recordは停止事実の記録として残る）。
    """
    from app.tools.browser.adapter import HUMAN_ONLY_PARAM_KEYS

    if not req.run_id or req.step_index is None:
        return
    if (result.data or {}).get("needs_confirmation"):
        return
    with _code_runs_lock:
        entry = _code_runs.get(req.run_id)
    if entry is None:
        return

    step_dict = {
        "index": req.step_index, "tool": "browser", "action": req.action,
        "params": {k: v for k, v in req.params.items()
                   if k not in HUMAN_ONLY_PARAM_KEYS},
        "ok": result.ok, "stubbed": result.stubbed, "output": result.output,
        "skipped": False, "skip_reason": "", "duration_s": 0.0,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "data": result.data,
    }

    with entry.lock:
        parent_record_id = entry.record_id
        if entry.status == "waiting_confirmation":
            target = next(
                (s for s in entry.steps if s.get("index") == req.step_index),
                None,
            )
            if target is not None:
                target.update(step_dict)
            # 既存ルールで再計算: 他に未承認ステップが無ければ done / failed
            still_waiting = any(
                (s.get("data") or {}).get("needs_confirmation")
                for s in entry.steps if not s.get("skipped")
            )
            if still_waiting:
                entry.status = "waiting_confirmation"
            else:
                executed = [s for s in entry.steps if not s.get("skipped")]
                run_ok = bool(executed) and all(s.get("ok") for s in executed) \
                    and not any(s.get("skipped") for s in entry.steps)
                entry.status = "done" if run_ok else "failed"

    _store.save(TaskRecord(
        task_text=f"承認後の実行: browser.{req.action}（{entry.task_text[:80]}）",
        task_kind="browser_confirm",
        model_name="",
        route_reason=f"人間の承認チャネル（親レコード: {parent_record_id or '不明'}"
                     f" / run: {req.run_id}）",
        tool_name="browser",
        tool_action=req.action,
        tool_ok=result.ok,
        tool_output=result.output,
        llm_output=f"browser.{req.action} 承認後の実行:"
                   f" {'成功' if result.ok else '失敗'}",
        stubbed=result.stubbed,
        plan_source="human",
        plan=[{"tool": "browser", "action": req.action,
               "params": step_dict["params"]}],
        step_results=[step_dict],
    ))


@app.post("/api/browser/confirm")
def post_browser_confirm(req: BrowserConfirmRequest) -> dict:
    """browser の承認済み再実行。/api/nachtcode/push と同型の人間チャネル。

    承認フラグ（domain_approved / confirmed / confirm_token）はこの
    エンドポイント自身が付与する。クライアントが params に紛れ込ませた
    承認フラグは必ず除去する（人間チャネル以外からの注入を遮断）。
    """
    from app.tools.base import ToolRequest
    from app.tools.browser.adapter import (
        HUMAN_ONLY_PARAM_KEYS,
        BrowserAdapter,
        add_domain_to_allowlist,
    )

    if req.action not in BrowserAdapter.supported_actions:
        raise HTTPException(status_code=400, detail=f"未知のaction: {req.action}")
    params = {k: v for k, v in req.params.items()
              if k not in HUMAN_ONLY_PARAM_KEYS}
    if req.kind == "domain":
        params["domain_approved"] = True
        if req.persist:
            # 恒久追記の対象は params の url から導出し、クライアントが
            # 無関係なドメインを追記させる余地を残さない
            from urllib.parse import urlsplit
            host = (urlsplit(str(params.get("url") or "")).hostname or "").lower()
            error = add_domain_to_allowlist(host)
            if error:
                raise HTTPException(status_code=400, detail=error)
    elif req.kind == "write":
        params["confirmed"] = True
        if req.confirm_token:
            params["confirm_token"] = req.confirm_token
    else:
        raise HTTPException(
            status_code=400, detail="kind は domain / write のいずれかです"
        )
    result = BrowserAdapter().execute(ToolRequest(
        action=req.action, params=params, task_text="UIからの承認"
    ))
    _record_confirm_result(req, result)
    return {"ok": result.ok, "output": result.output, "data": result.data}


@app.get("/api/nachtcode/github-repos")
def get_github_repos() -> dict:
    """GitHubリポジトリ一覧（読み取りのみ）。{run_id} ルートより先に定義。"""
    from app.tools.base import ToolRequest
    from app.tools.nachtcode.adapter import NachtCodeAdapter

    result = NachtCodeAdapter().execute(
        ToolRequest(action="list_github_repos", params={}, task_text="UI")
    )
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.output)
    return {"stubbed": result.stubbed,
            "repos": result.data.get("repos", []),
            "output": result.output if result.stubbed else ""}


class CloneRequest(BaseModel):
    repo: str  # "owner/name"


@app.post("/api/nachtcode/clone")
def post_nachtcode_clone(req: CloneRequest) -> dict:
    """リポジトリを ~/nachtcode-repos/ にクローン（既存があれば再利用）。"""
    from app.tools.base import ToolRequest
    from app.tools.nachtcode.adapter import NachtCodeAdapter

    result = NachtCodeAdapter().execute(
        ToolRequest(action="clone_repo", params={"repo": req.repo},
                    task_text="UIからのクローン")
    )
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.output)
    return {"ok": True, "stubbed": result.stubbed, "output": result.output,
            "dir": result.data.get("dir", ""),
            "reused": result.data.get("reused", "")}


@app.get("/api/nachtcode/{run_id}")
def get_nachtcode_run(run_id: str) -> dict:
    with _code_runs_lock:
        entry = _code_runs.get(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="run が見つかりません")
    with entry.lock:
        result = {
            "run_id": entry.run_id,
            "status": entry.status,
            "error": entry.error,
            "dir": entry.target_dir,
            "task_text": entry.task_text,
            "started_at": entry.started_at,
            "record_id": entry.record_id,
            # 実行中の途中経過。完了後は下のレコード由来の値で上書きされる
            # （内容は同じで、summary が加わる）。
            "plan": list(entry.plan),
            "steps": list(entry.steps),
        }
    if result["record_id"]:
        record = _store.load_by_id(result["record_id"])
        if record:
            result["summary"] = record.get("llm_output", "")
            result["plan"] = record.get("plan", [])
            # steps は entry 側が正（承認後の実行結果で更新され得る）。
            # record のスナップショットは entry が空のときだけ使う。
            if not result["steps"]:
                result["steps"] = record.get("step_results", [])
    return result


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


@app.delete("/api/tasks/{record_id}")
def delete_task(record_id: str) -> dict:
    """タスク1件を削除する（一括削除・条件削除は提供しない）。"""
    with _runs_lock:
        active = any(
            e.record_id == record_id and e.status == "running"
            for e in _runs.values()
        )
    with _code_runs_lock:
        active = active or any(
            e.record_id == record_id and e.status == "running"
            for e in _code_runs.values()
        )
    if active:
        raise HTTPException(
            status_code=409, detail="実行中のタスクは削除できません"
        )
    deleted = _store.delete_task(record_id)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="タスクが見つかりません")
    return {"id": record_id, "deleted": deleted}


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
