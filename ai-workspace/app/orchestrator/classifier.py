"""タスク分類。

PoC段階はキーワードベースのルール分類。
将来は「軽量ローカルLLMによる分類」に差し替える予定だが、
classify_task() のシグネチャ（str -> TaskKind + ツールヒント）は維持する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class TaskKind(str, Enum):
    CODE = "code"              # コード読解・レビュー・リポジトリ操作（読む側）
    CODING = "coding"          # Nacht Code: コードを書く・編集する側
    WRITE_NOTE = "write_note"  # メモ・ドキュメントの作成/保存
    AUTOMATION = "automation"  # n8n 等のワークフロー起動
    BROWSER = "browser"        # Web閲覧・操作（今日は stub）
    GENERAL = "general"        # 上記以外の一般対話


@dataclass(frozen=True)
class Classification:
    kind: TaskKind
    tool_name: str | None      # 使うべきツール（不要なら None）
    tool_action: str | None    # ツールに渡す action


# キーワード -> 分類。マッチしたキーワード数が最多のルールを採用し、
# 同数の場合は上のルールを優先する。
_RULES: list[tuple[tuple[str, ...], Classification]] = [
    (
        # Nacht Code（コードを「書く・編集する」）。GitHub の「読む」系と区別する
        ("実装して", "リファクタ", "コードを修正", "コードを書いて",
         "コードを直して", "テストを直して", "バグを直して", "コメントを追加",
         "docstring", ".py", "関数に"),
        Classification(TaskKind.CODING, "noircode", "list_files"),
    ),
    (
        ("github", "リポジトリ", "readme", "プルリク", "pull request", "issue"),
        Classification(TaskKind.CODE, "github", "read_readme"),
    ),
    (
        ("検索して", "探して", "検索"),
        Classification(TaskKind.WRITE_NOTE, "obsidian", "search_notes"),
    ),
    (
        ("追記して", "追記"),
        Classification(TaskKind.WRITE_NOTE, "obsidian", "append_note"),
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

# 引用符で囲まれた部分（メモのタイトル等の「データ」）。
# 例:「Obsidianに『GitHub確認完了』というメモを保存して」の『…』内は
# タスクの意図ではないため、キーワード判定の対象から外す。
_QUOTED_SPAN = re.compile(
    r"『[^』]*』|「[^」]*」|【[^】]*】|“[^”]*”|\"[^\"]*\"|'[^']*'"
)


def _intent_text(task_text: str) -> str:
    """引用部分を除いた、意図判定用のテキストを返す。"""
    return _QUOTED_SPAN.sub(" ", task_text)


def classify_task(task_text: str) -> Classification:
    """自然言語タスクを分類し、使用ツールのヒントを返す。"""
    lowered = _intent_text(task_text).lower()
    best = _FALLBACK
    best_score = 0
    for keywords, classification in _RULES:
        score = sum(1 for kw in keywords if kw in lowered)
        if score > best_score:
            best, best_score = classification, score
    return best
