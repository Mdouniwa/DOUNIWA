"""n8n アダプタ（stub + 最小接続口）。

最小接続は「Mac mini 上の n8n の Webhook URL を POST で叩く」こと。
N8N_WEBHOOK_BASE_URL が未設定なら stub 応答。

将来拡張（docs/roadmap.md 参照）:
  - n8n REST API 経由のワークフロー一覧・実行・監視
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
    supported_actions = ("trigger_webhook",)
    action_docs = {
        "trigger_webhook": (
            "n8n の Webhook を POST で起動する。"
            ' params: {"webhook_path": "Webhookのパス", "payload": {任意のJSON}}'
        ),
    }
    write_actions = ("trigger_webhook",)

    def execute(self, request: ToolRequest) -> ToolResult:
        if request.action == "trigger_webhook":
            return self._trigger_webhook(request)
        return ToolResult(ok=False, output=f"unknown action: {request.action}")

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
