"""実行ログの保存。

PoC段階では JSONL への追記のみ。1タスク=1レコード。
保存ルール:
  - 保存先: MEMORY_DIR（既定 ./data/memory）配下の runs-YYYY-MM.jsonl（月次ローテーション）
  - 機微情報を含み得るため、data/ は .gitignore 済み・ローカルのみに置く
  - レコードは追記のみ。書き換え・削除はしない（監査可能性のため）

将来拡張:
  - SQLite 化と検索API
  - セッション（複数ターン会話）の文脈保持
  - Obsidian への自動サマリー書き出し
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TaskRecord:
    """1タスク実行分の記録。"""

    task_text: str
    task_kind: str
    model_name: str
    route_reason: str
    tool_name: str | None
    tool_action: str | None
    tool_output: str
    llm_output: str
    stubbed: bool
    tool_ok: bool | None = None  # ツール未使用なら None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class MemoryStore:
    def __init__(self, base_dir: str | Path | None = None) -> None:
        base = base_dir or os.environ.get("MEMORY_DIR", "data/memory")
        self._dir = Path(base)

    def save(self, record: TaskRecord) -> Path:
        """レコードを月次JSONLに追記し、書き込んだファイルパスを返す。"""
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"runs-{datetime.now():%Y-%m}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        logger.info("実行ログを保存しました: %s (id=%s)", path, record.id)
        return path
