"""実行ログの保存。

PoC段階では JSONL への追記。1タスク=1レコード。
保存ルール:
  - 保存先: MEMORY_DIR（既定 ./data/memory）配下の runs-YYYY-MM.jsonl（月次ローテーション）
  - 機微情報を含み得るため、data/ は .gitignore 済み・ローカルのみに置く
  - レコードは原則追記のみ（監査可能性のため）。唯一の例外は
    delete_session() で、ユーザーが明示的に指定した会話（session_id 付き）の
    レコードだけを取り除く。session_id を持たないレガシー記録は絶対に触らない。

セッション:
  - session_id はWeb UIの「会話」単位。空文字はセッション概念導入前の
    レガシー記録および CLI 実行を表す。

将来拡張:
  - SQLite 化と検索API
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
    session_id: str = ""         # 会話ID（空 = レガシー記録またはCLI実行）
    plan_source: str = ""        # "llm" | "rules" | "fast"（実行計画の生成方式）
    plan_note: str = ""          # フォールバック理由・拒否理由等
    # 人間の承認待ちで停止した run の記録（成功/失敗の2値に畳まない）。
    # 承認後の実行は別レコードとして追記される（このレコードは書き換えない）。
    waiting_confirmation: bool = False
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

    def load_recent(
        self,
        n: int = 3,
        session_id: str | None = None,
        any_session: bool = False,
    ) -> list[dict]:
        """直近のタスク記録を古い順で最大 n 件返す。

        - session_id 指定: その会話の記録だけ（会話の継続性用。
          他の会話のタスクがコンテキストへ混入しないための仕様）
        - session_id なし: session_id を持たない記録（レガシー/CLI実行）だけ
        - any_session=True: セッションに関係なく全記録（タスク一覧の表示用）
        新しい月次ファイルから遡って読む。壊れた行は読み飛ばす。
        """
        if n <= 0:
            return []
        want = session_id or ""
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
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not any_session and (record.get("session_id") or "") != want:
                    continue
                records.append(record)
                if len(records) >= n:
                    return list(reversed(records))
        return list(reversed(records))

    def _iter_records(self):
        """全レコードを古い順で列挙する（壊れた行は読み飛ばす）。"""
        for path in sorted(self._dir.glob("runs-*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def list_sessions(self) -> list[dict]:
        """会話（session_id 付き記録）の一覧を新しい順で返す。

        レガシー記録（session_id なし）は一覧に含めない。
        """
        sessions: dict[str, dict] = {}
        for record in self._iter_records():
            sid = record.get("session_id") or ""
            if not sid:
                continue
            entry = sessions.setdefault(sid, {
                "session_id": sid,
                "title": record.get("task_text", "")[:60],
                "started_at": record.get("timestamp", ""),
                "count": 0,
            })
            entry["count"] += 1
            entry["last_at"] = record.get("timestamp", "")
        return sorted(
            sessions.values(), key=lambda s: s.get("last_at", ""), reverse=True
        )

    def load_session(self, session_id: str) -> list[dict]:
        """指定した会話の全レコードを古い順で返す。"""
        if not session_id:
            return []
        return [
            r for r in self._iter_records()
            if (r.get("session_id") or "") == session_id
        ]

    def delete_task(self, record_id: str) -> int:
        """指定したIDのレコード1件だけを削除し、削除件数を返す。

        delete_session() と同じく、追記のみ原則の例外（ユーザーの明示操作専用）。
        record_id が空なら何もしない。対象行以外（壊れた行を含む）は
        そのまま書き戻す。一括削除・条件削除は実装しない。
        """
        if not record_id:
            return 0
        deleted = 0
        for path in sorted(self._dir.glob("runs-*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            kept: list[str] = []
            removed_here = 0
            for line in lines:
                stripped = line.strip()
                if stripped:
                    try:
                        record = json.loads(stripped)
                    except json.JSONDecodeError:
                        kept.append(line)  # 壊れた行も消さない
                        continue
                    if record.get("id") == record_id:
                        removed_here += 1
                        continue
                kept.append(line)
            if removed_here:
                content = "\n".join(kept)
                if content:
                    content += "\n"
                path.write_text(content, encoding="utf-8")
                deleted += removed_here
                logger.info(
                    "タスク %s のレコードを %s から削除しました", record_id, path
                )
        return deleted

    def delete_session(self, session_id: str) -> int:
        """指定した会話のレコードだけを削除し、削除件数を返す。

        追記のみ原則の唯一の例外（ユーザーの明示操作専用）。
        session_id が空の場合は何もしない — レガシー記録（session_id なし）を
        誤って一括削除しないための安全弁。他の会話・レガシー記録の行は
        バイト単位でそのまま書き戻す。
        """
        if not session_id:
            return 0
        deleted = 0
        for path in sorted(self._dir.glob("runs-*.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            kept: list[str] = []
            removed_here = 0
            for line in lines:
                stripped = line.strip()
                if stripped:
                    try:
                        record = json.loads(stripped)
                    except json.JSONDecodeError:
                        kept.append(line)  # 壊れた行も消さない
                        continue
                    if (record.get("session_id") or "") == session_id:
                        removed_here += 1
                        continue
                kept.append(line)
            if removed_here:
                content = "\n".join(kept)
                if content:
                    content += "\n"
                path.write_text(content, encoding="utf-8")
                deleted += removed_here
                logger.info(
                    "会話 %s のレコード %d 件を %s から削除しました",
                    session_id, removed_here, path,
                )
        return deleted
