"""GitHub アダプタ（stub + 最小接続口）。

現状:
  - GITHUB_TOKEN が設定されていれば GitHub REST API で README を実取得できる
  - 未設定なら stub 応答

将来拡張（docs/roadmap.md 参照）:
  - issue / PR の読み書き
  - リポジトリ横断検索
  - ローカル clone に対する git 操作
"""

from __future__ import annotations

import base64
import logging
import os

import httpx

from app.tools.base import ToolAdapter, ToolRequest, ToolResult

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"


class GitHubAdapter(ToolAdapter):
    name = "github"
    supported_actions = ("read_readme",)

    def execute(self, request: ToolRequest) -> ToolResult:
        if request.action == "read_readme":
            return self._read_readme(request)
        return ToolResult(ok=False, output=f"unknown action: {request.action}")

    def _read_readme(self, request: ToolRequest) -> ToolResult:
        repo = request.params.get("repo") or os.environ.get("GITHUB_DEFAULT_REPO")
        token = os.environ.get("GITHUB_TOKEN")

        if not repo or not token:
            missing = "GITHUB_DEFAULT_REPO/repo指定" if not repo else "GITHUB_TOKEN"
            return ToolResult(
                ok=True,
                stubbed=True,
                output=(
                    f"[stub:github] {missing} が未設定のため stub 応答です。"
                    " READMEを取得したものとして処理を継続します。"
                ),
            )

        try:
            resp = httpx.get(
                f"{_API_BASE}/repos/{repo}/readme",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return ToolResult(
                ok=True,
                output=content,
                data={"repo": repo, "path": data.get("path", "README.md")},
            )
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("GitHub README 取得に失敗: %s", exc)
            return ToolResult(
                ok=False,
                output=f"GitHub README 取得に失敗しました ({repo}): {exc}",
            )
