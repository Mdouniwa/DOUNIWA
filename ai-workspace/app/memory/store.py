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
    plan_source: str = ""        # "llm" | "rules"（実行計画の生成方式）
    plan_note: str = ""          # フォールバック理由・拒否理由等
    plan: list = field(default_factory=list)          # 計画ステップの一覧
    step_results: list = field(default_factory=list)  # ステップごとの実行事実
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

    def load_by_id(self, record_id: str) -> dict | None:
        """レコードIDで1件検索する。新しいファイルから遡って探す。"""
        for path in sorted(self._dir.glob("runs-*.jsonl"), reverse=True):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("id") == record_id:
                    return record
        return None

    def load_recent(self, n: int = 3) -> list[dict]:
        """直近のタスク記録を古い順で最大 n 件返す（会話の継続性用）。

        新しい月次ファイルから遡って読む。壊れた行は読み飛ばす。
        """
        if n <= 0:
            return []
        records: list[dict] = []
        for path in sorted(self._dir.glob("runs-*.jsonl"), reverse=True):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(records) >= n:
                    return list(reversed(records))
        return list(reversed(records))
