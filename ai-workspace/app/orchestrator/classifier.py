"""タスク分類。

PoC段階はキーワードベースのルール分類。
将来は「軽量ローカルLLMによる分類」に差し替える予定だが、
classify_task() のシグネチャ（str -> TaskKind + ツールヒント）は維持する。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskKind(str, Enum):
    CODE = "code"              # コード読解・レビュー・リポジトリ操作
    WRITE_NOTE = "write_note"  # メモ・ドキュメントの作成/保存
    AUTOMATION = "automation"  # n8n 等のワークフロー起動
    BROWSER = "browser"        # Web閲覧・操作（今日は stub）
    GENERAL = "general"        # 上記以外の一般対話


@dataclass(frozen=True)
class Classification:
    kind: TaskKind
    tool_name: str | None      # 使うべきツール（不要なら None）
    tool_action: str | None    # ツールに渡す action


# キーワード -> 分類。上から順に評価し、最初にマッチしたものを採用する。
_RULES: list[tuple[tuple[str, ...], Classification]] = [
    (
        ("github", "リポジトリ", "readme", "プルリク", "pull request", "issue"),
        Classification(TaskKind.CODE, "github", "read_readme"),
    ),
    (
        ("obsidian", "メモ", "ノート", "保存して", "書き留め"),
        Classification(TaskKind.WRITE_NOTE, "obsidian", "save_note"),
    ),
    (
        ("n8n", "webhook", "ワークフロー", "自動化"),
        Classification(TaskKind.AUTOMATION, "n8n", "trigger_webhook"),
    ),
    (
        ("ブラウザ", "browser", "webページ", "スクレイピング", "クリックして"),
        Classification(TaskKind.BROWSER, "browser", "open_url"),
    ),
]

_FALLBACK = Classification(TaskKind.GENERAL, None, None)


def classify_task(task_text: str) -> Classification:
    """自然言語タスクを分類し、使用ツールのヒントを返す。"""
    lowered = task_text.lower()
    for keywords, classification in _RULES:
        if any(kw in lowered for kw in keywords):
            return classification
    return _FALLBACK
