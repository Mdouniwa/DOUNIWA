"""n8n アダプタ（stub + 最小接続口）。

対応 action:
  - trigger_webhook: Webhook URL を POST で叩く（N8N_WEBHOOK_BASE_URL）
  - list_workflows : REST API でワークフロー一覧を取得
                     （N8N_API_BASE_URL + N8N_API_KEY。未設定なら stub）

将来拡張（docs/roadmap.md 参照）:
  - ワークフローの実行・監視（REST API）
  - 実行結果のポーリングと memory 層への詳細記録
"""

from __future__ import annotations

import logging
import os

import httpx

from app.tools.base import ToolAdapter, ToolRequest, ToolResult

logger = logging.getLogger(__name__)


class N8nAdapter(ToolAdapter):
    name = "n8n"
    supported_actions = ("trigger_webhook", "list_workflows")
    action_docs = {
        "trigger_webhook": (
            "n8n の Webhook を POST で起動する。"
            ' params: {"webhook_path": "Webhookのパス", "payload": {任意のJSON}}'
        ),
        "list_workflows": (
            "n8n に登録済みのワークフロー一覧（名前・有効/無効）を取得する。"
            " params: {}"
        ),
    }
    write_actions = ("trigger_webhook",)

    def execute(self, request: ToolRequest) -> ToolResult:
        if request.action == "trigger_webhook":
            return self._trigger_webhook(request)
        if request.action == "list_workflows":
            return self._list_workflows(request)
        return ToolResult(ok=False, output=f"unknown action: {request.action}")

    def _list_workflows(self, request: ToolRequest) -> ToolResult:
        base = os.environ.get("N8N_API_BASE_URL")
        api_key = os.environ.get("N8N_API_KEY")
        if not base or not api_key:
            missing = "N8N_API_BASE_URL" if not base else "N8N_API_KEY"
            return ToolResult(
                ok=True,
                stubbed=True,
                output=(
                    f"[stub:n8n] {missing} が未設定のため stub 応答です。"
                    " ワークフロー一覧は実際には取得していません。"
                ),
            )

        url = base.rstrip("/") + "/workflows"
        try:
            resp = httpx.get(
                url, headers={"X-N8N-API-KEY": api_key}, timeout=30.0
            )
            resp.raise_for_status()
            payload = resp.json()
            workflows = payload.get("data", payload) or []
            if not isinstance(workflows, list):
                return ToolResult(
                    ok=False,
                    output=f"n8n API の応答形式が想定外です: {str(payload)[:200]}",
                )
            lines = [f"n8n ワークフロー一覧（{len(workflows)}件）:"]
            for wf in workflows:
                active = "有効" if wf.get("active") else "無効"
                lines.append(
                    f"- {wf.get('name', '(無名)')} [{active}] id={wf.get('id')}"
                )
            return ToolResult(
                ok=True,
                output="\n".join(lines),
                data={"count": len(workflows)},
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("n8n ワークフロー一覧の取得に失敗: %s", exc)
            return ToolResult(
                ok=False,
                output=f"n8n ワークフロー一覧の取得に失敗しました ({url}): {exc}",
            )

    def _trigger_webhook(self, request: ToolRequest) -> ToolResult:
        base = os.environ.get("N8N_WEBHOOK_BASE_URL")
        path = request.params.get("webhook_path", "")

        if not base:
            return ToolResult(
                ok=True,
                stubbed=True,
                output=(
                    "[stub:n8n] N8N_WEBHOOK_BASE_URL が未設定のため stub 応答です。"
                    f" 叩く予定だった webhook: '{path or '(未指定)'}'"
                ),
            )

        url = base.rstrip("/") + "/" + path.lstrip("/")
        payload = {"task": request.task_text, **request.params.get("payload", {})}
        try:
            resp = httpx.post(url, json=payload, timeout=60.0)
            resp.raise_for_status()
            return ToolResult(
                ok=True,
                output=f"n8n webhook 実行成功 ({url}): HTTP {resp.status_code}",
                data={"status_code": resp.status_code, "body": resp.text[:2000]},
            )
        except httpx.HTTPError as exc:
            logger.warning("n8n webhook 実行に失敗: %s", exc)
            return ToolResult(ok=False, output=f"n8n webhook 実行に失敗しました: {exc}")
