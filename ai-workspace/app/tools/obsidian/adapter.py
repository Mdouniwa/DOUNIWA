"""Obsidian アダプタ（stub + 最小接続口）。

Obsidian vault はただのディレクトリなので、最小接続は
「OBSIDIAN_VAULT_PATH 配下に Markdown を書く」ことで成立する。
vault が未設定・存在しない場合は stub 応答。

将来拡張（docs/roadmap.md 参照）:
  - Mac mini 側 vault への書き込み（Syncthing/iCloud 経由 or REST プラグイン）
  - ノート検索・既存ノートへの追記
  - デイリーノート/テンプレート対応
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from app.tools.base import ToolAdapter, ToolRequest, ToolResult

logger = logging.getLogger(__name__)


class ObsidianAdapter(ToolAdapter):
    name = "obsidian"
    supported_actions = ("save_note",)

    def execute(self, request: ToolRequest) -> ToolResult:
        if request.action == "save_note":
            return self._save_note(request)
        return ToolResult(ok=False, output=f"unknown action: {request.action}")

    def _save_note(self, request: ToolRequest) -> ToolResult:
        vault = os.environ.get("OBSIDIAN_VAULT_PATH")
        title = request.params.get("title") or f"ai-workspace {datetime.now():%Y-%m-%d %H%M}"
        body = request.params.get("body") or request.task_text

        if not vault or not Path(vault).is_dir():
            return ToolResult(
                ok=True,
                stubbed=True,
                output=(
                    "[stub:obsidian] OBSIDIAN_VAULT_PATH が未設定または存在しないため"
                    f" stub 応答です。保存予定ノート: '{title}'"
                ),
                data={"title": title},
            )

        folder = Path(vault) / os.environ.get("OBSIDIAN_NOTE_FOLDER", "ai-workspace")
        folder.mkdir(parents=True, exist_ok=True)
        safe_title = "".join(c for c in title if c not in '\\/:*?"<>|').strip()
        path = folder / f"{safe_title}.md"
        try:
            path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
            return ToolResult(
                ok=True,
                output=f"Obsidian ノートを保存しました: {path}",
                data={"path": str(path)},
            )
        except OSError as exc:
            logger.warning("Obsidian ノート保存に失敗: %s", exc)
            return ToolResult(ok=False, output=f"ノート保存に失敗しました: {exc}")
