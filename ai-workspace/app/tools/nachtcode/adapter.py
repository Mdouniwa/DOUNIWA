"""Nacht Code — 対象ディレクトリ限定のコーディングエージェント用アダプタ。

ai-workspace (kuro·console) と並ぶ2つ目のエージェント。強い権限
（ファイル編集）を持つため、既存のオーケストレーターとは明確に切り分け、
以下の3段階の権限方針を厳守する:

  1. 自動実行してよい:
     read_file / list_files / edit_file / run_tests（pytest固定）
  2. 自動実行するが監査ログ（NACHTCODE_AUDIT_DIR、既定 data/nachtcode）に残す:
     create_file / git_commit（および edit_file の diff も記録する）
  3. 実装しない（actionとして存在させない）:
     git push・ファイル削除/移動（rm/mv）・外部コマンド実行
     （npm/pip install等）・対象ディレクトリ外へのアクセス・システムコマンド

【2026-07-18 方針変更】権限を Claude Code と同等の運用に変更した。
上記レベル3は Cursor 共作初期の一時的な安全策であり、現在は:
  - delete_file / delete_dir / run_command は自動実行（全件監査ログ記録）
  - git_push は「明示的な確認を経てのみ」実行。params の confirmed が
    True でない限りプレビューを返すだけで絶対に push しない。
    confirmed は人間の確認チャネル（CLIの y/n 入力・UIの確認ダイアログ）
    だけが注入でき、LLMが計画に書いた confirmed は計画パース時に
    強制除去される。無人での自動 push は行わない。
  - 維持される制約: 対象ディレクトリの明示・危険ディレクトリ拒否・
    resolve() 後のパストラバーサル/シンボリックリンク脱出拒否は
    すべての action に適用。delete_dir は対象ディレクトリ自体を消せない。
  - run_command は cwd を対象ディレクトリに固定し全コマンドを監査するが、
    OSプロセスとして動く以上、コマンド自身の副作用（キャッシュ書き込み等）
    の完全封じ込めは技術的に不可能（Claude Code と同じ性質）。

対象ディレクトリはタスクごとに params の "dir" で明示させる。
デフォルト対象は存在しない。パス検証は resolve() 後に行い、
../ やシンボリックリンクによる脱出を拒否する。
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app.tools.base import ToolAdapter, ToolRequest, ToolResult

logger = logging.getLogger(__name__)

_MAX_READ_CHARS = 100_000
_MAX_LIST_ENTRIES = 300
_MAX_OUTPUT_CHARS = 4000
_TEST_TIMEOUT_S = 180
_GIT_TIMEOUT_S = 30
_COMMAND_TIMEOUT_S = 300
_PUSH_TIMEOUT_S = 120

#: 一覧・探索で無視するディレクトリ
_IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
                 ".pytest_cache", ".mypy_cache", "dist", "build", ".idea"}

_HOME = Path.home().resolve()

#: 対象ディレクトリとして拒否する場所（そのものを指した場合）
_BANNED_EXACT = {
    Path("/"), _HOME, Path("/tmp"), Path("/private/tmp"),
    Path("/var"), Path("/private"), Path("/private/var"),
}

#: 対象ディレクトリとして拒否する場所（配下も含めて）
_BANNED_SUBTREES = [
    Path("/etc"), Path("/private/etc"), Path("/usr"), Path("/bin"),
    Path("/sbin"), Path("/opt"), Path("/System"), Path("/Library"),
    Path("/Applications"), _HOME / "Library",
]

#: 例外的に許可する一時領域（/tmp・pytest の tmp_path 配下）
_ALLOWED_TMP = [Path("/private/tmp"), Path("/tmp"), Path("/private/var/folders")]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_project_dir(raw: str) -> tuple[Path | None, str]:
    """対象ディレクトリを検証する。(resolved, "") か (None, エラー文)。"""
    if not raw or not str(raw).strip():
        return None, 'params {"dir": "対象プロジェクトの絶対パス"} が必要です'
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        return None, f"対象ディレクトリは絶対パスで指定してください: {raw}"
    resolved = path.resolve()
    if not resolved.is_dir():
        return None, f"対象ディレクトリが存在しません: {resolved}"
    if resolved in _BANNED_EXACT:
        return None, f"このディレクトリは対象にできません（安全ガード）: {resolved}"
    in_tmp = any(_is_within(resolved, t) and resolved != t for t in _ALLOWED_TMP)
    if not in_tmp:
        for banned in _BANNED_SUBTREES:
            if _is_within(resolved, banned):
                return None, (
                    f"このディレクトリは対象にできません（安全ガード）: {resolved}"
                )
    return resolved, ""


def _resolve_inside(root: Path, raw_path: str) -> tuple[Path | None, str]:
    """root 配下のファイルパスを解決する。脱出（../・symlink・絶対パス）は拒否。"""
    if not raw_path or not str(raw_path).strip():
        return None, 'params {"path": "ディレクトリ内の相対パス"} が必要です'
    candidate = Path(str(raw_path))
    target = candidate if candidate.is_absolute() else root / candidate
    # 存在しないファイル（新規作成）でも親を辿って解決できるよう resolve は
    # strict=False。resolve 後に root 配下かを検証する。
    resolved = target.resolve()
    if not _is_within(resolved, root) or resolved == root:
        return None, (
            f"対象ディレクトリの外は操作できません（安全ガード）: {raw_path}"
        )
    return resolved, ""


def _audit(action: str, root: Path, detail: dict) -> None:
    """権限レベル2の操作（および全変更系）を監査ログへ逐次記録する。"""
    audit_dir = Path(os.environ.get("NACHTCODE_AUDIT_DIR", "data/nachtcode"))
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "dir": str(root),
            **detail,
        }
        path = audit_dir / f"audit-{datetime.now():%Y-%m}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("Nacht Code 監査ログの書き込みに失敗: %s", exc)


import re as _re

_FENCED_BLOCK = _re.compile(r"```[^\n]*\n(.*?)\n?```", _re.DOTALL)


def _strip_code_fences(text: str) -> str:
    """LLM生成コンテンツからコード本体を取り出す。

    - 全体が ```...``` で囲まれている場合はフェンスを外す
    - 「説明文 + ```コード```」形式の場合は、フェンス内が本体の過半を
      占めるときに限りフェンス内だけを採用する（LLMが指示を無視して
      前置きを付けるケースへの防御。Markdown編集等でフェンスが本文の
      一部である場合は誤爆しないよう長さ比で判定する）
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:]  # ```python 等の行
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines) + "\n"
    m = _FENCED_BLOCK.search(stripped)
    if m:
        inner = m.group(1)
        outside = len(stripped) - len(m.group(0))
        if len(inner) >= outside:
            return inner + "\n"
    return text


def _unified_diff(old: str, new: str, path: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}",
    )
    return "".join(lines)


class NachtCodeAdapter(ToolAdapter):
    name = "nachtcode"
    supported_actions = (
        "read_file", "list_files", "edit_file",
        "create_file", "run_tests", "git_commit",
        "delete_file", "delete_dir", "run_command", "git_push",
    )
    action_docs = {
        "read_file": (
            "[Nacht Code] 対象プロジェクト内のファイルを読む。"
            ' params: {"dir": "対象プロジェクトの絶対パス", "path": "相対パス"}'
        ),
        "list_files": (
            "[Nacht Code] 対象プロジェクトのファイル構成を一覧する。"
            ' params: {"dir": "対象プロジェクトの絶対パス"}'
        ),
        "edit_file": (
            "[Nacht Code] 既存ファイルを編集する。小さな置換は"
            ' {"dir": "...", "path": "相対パス", "old_string": "置換前（一意）",'
            ' "new_string": "置換後"}。ファイル全体の書き換えは'
            ' {"dir": "...", "path": "相対パス", "content": "新しい全内容"}'
            "（content には {{stepN.output}} で llm.generate の出力を渡せる）"
        ),
        "create_file": (
            "[Nacht Code] 新規ファイルを作成する（既存ファイルは上書きしない）。"
            ' params: {"dir": "...", "path": "相対パス", "content": "内容"}'
        ),
        "run_tests": (
            "[Nacht Code] 対象プロジェクトの pytest を実行する（それ以外の"
            "コマンドは実行できない）。"
            ' params: {"dir": "対象プロジェクトの絶対パス"}'
        ),
        "git_commit": (
            "[Nacht Code] 変更を git commit する（push は git_push を使う）。"
            ' params: {"dir": "...", "message": "コミットメッセージ"}'
        ),
        "delete_file": (
            "[Nacht Code] 対象プロジェクト内のファイルを1つ削除する。"
            ' params: {"dir": "...", "path": "相対パス"}'
        ),
        "delete_dir": (
            "[Nacht Code] 対象プロジェクト内のディレクトリを削除する"
            "（対象ディレクトリ自体は削除できない）。"
            ' params: {"dir": "...", "path": "相対パス"}'
        ),
        "run_command": (
            "[Nacht Code] 開発用コマンドを対象ディレクトリ内で実行する"
            "（npm install / pip install 等。cwd は対象ディレクトリ固定）。"
            ' params: {"dir": "...", "command": "実行するコマンド"}'
        ),
        "git_push": (
            "[Nacht Code] git push する。必ず確認ステップを経る: "
            "まずプレビュー（remote・ブランチ・送信コミット）が返り、"
            "人間が確認した場合のみ実行される。"
            ' params: {"dir": "...", "remote": "省略時origin", "branch": "省略時現在のブランチ"}'
        ),
    }
    write_actions = ("edit_file", "create_file", "git_commit",
                     "delete_file", "delete_dir", "run_command", "git_push")

    def execute(self, request: ToolRequest) -> ToolResult:
        root, error = validate_project_dir(request.params.get("dir", ""))
        if error:
            return ToolResult(ok=False, output=f"[Nacht Code] {error}")
        handler = {
            "read_file": self._read_file,
            "list_files": self._list_files,
            "edit_file": self._edit_file,
            "create_file": self._create_file,
            "run_tests": self._run_tests,
            "git_commit": self._git_commit,
            "delete_file": self._delete_file,
            "delete_dir": self._delete_dir,
            "run_command": self._run_command,
            "git_push": self._git_push,
        }.get(request.action)
        if handler is None:
            return ToolResult(ok=False, output=f"unknown action: {request.action}")
        return handler(root, request)

    # ------------------------------------------------------------------
    # レベル1: 読み取り・テスト
    # ------------------------------------------------------------------

    def _read_file(self, root: Path, request: ToolRequest) -> ToolResult:
        path, error = _resolve_inside(root, request.params.get("path", ""))
        if error:
            return ToolResult(ok=False, output=f"[Nacht Code] {error}")
        if not path.is_file():
            return ToolResult(
                ok=False, output=f"[Nacht Code] ファイルが存在しません: {path}"
            )
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult(ok=False, output=f"[Nacht Code] 読み取り失敗: {exc}")
        clipped = text[:_MAX_READ_CHARS]
        note = "" if len(text) <= _MAX_READ_CHARS else "\n…（以降省略）"
        rel = path.relative_to(root)
        return ToolResult(
            ok=True,
            output=f"{rel}:\n{clipped}{note}",
            data={"dir": str(root), "path": str(rel), "bytes": len(text)},
        )

    def _list_files(self, root: Path, request: ToolRequest) -> ToolResult:
        entries: list[str] = []
        truncated = False
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in _IGNORED_DIRS)
            rel_dir = Path(dirpath).relative_to(root)
            for name in sorted(filenames):
                if name.startswith(".DS_Store"):
                    continue
                rel = str(rel_dir / name) if str(rel_dir) != "." else name
                entries.append(rel)
                if len(entries) >= _MAX_LIST_ENTRIES:
                    truncated = True
                    break
            if truncated:
                break
        listing = "\n".join(entries)
        if truncated:
            listing += f"\n…（{_MAX_LIST_ENTRIES}件で打ち切り）"
        return ToolResult(
            ok=True,
            output=f"{root} のファイル一覧（{len(entries)}件）:\n{listing}",
            data={"dir": str(root), "count": len(entries)},
        )

    def _run_tests(self, root: Path, request: ToolRequest) -> ToolResult:
        # 実行できるのは pytest のみ（ホワイトリスト方式・shell不使用）。
        # 任意コマンドの実行口は設けない。
        venv_pytest = root / ".venv" / "bin" / "pytest"
        if venv_pytest.is_file():
            cmd = [str(venv_pytest), "-q"]
        else:
            cmd = [sys.executable, "-m", "pytest", "-q"]
        try:
            proc = subprocess.run(
                cmd, cwd=str(root), capture_output=True, text=True,
                timeout=_TEST_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                ok=False,
                output=f"[Nacht Code] pytest が{_TEST_TIMEOUT_S}秒で完了しませんでした",
            )
        except OSError as exc:
            return ToolResult(ok=False, output=f"[Nacht Code] pytest 起動失敗: {exc}")
        output = (proc.stdout + proc.stderr)[-_MAX_OUTPUT_CHARS:]
        ok = proc.returncode == 0
        return ToolResult(
            ok=ok,
            output=f"pytest exit={proc.returncode}\n{output}",
            data={"dir": str(root), "exit_code": proc.returncode},
        )

    # ------------------------------------------------------------------
    # レベル1/2: 変更系（すべて監査ログへ diff を記録）
    # ------------------------------------------------------------------

    def _edit_file(self, root: Path, request: ToolRequest) -> ToolResult:
        path, error = _resolve_inside(root, request.params.get("path", ""))
        if error:
            return ToolResult(ok=False, output=f"[Nacht Code] {error}")
        if not path.is_file():
            return ToolResult(
                ok=False,
                output=(
                    f"[Nacht Code] ファイルが存在しません: {path}"
                    "（新規作成は create_file を使ってください）"
                ),
            )
        old_string = request.params.get("old_string", "")
        new_string = request.params.get("new_string", "")
        content = request.params.get("content", "")
        if not old_string and not content:
            return ToolResult(
                ok=False,
                output=(
                    '[Nacht Code] edit_file には {"old_string","new_string"}（置換）'
                    'または {"content"}（全体書き換え）のどちらかが必要です'
                ),
            )
        try:
            original = path.read_text(encoding="utf-8")
        except OSError as exc:
            return ToolResult(ok=False, output=f"[Nacht Code] 読み取り失敗: {exc}")
        if old_string:
            count = original.count(old_string)
            if count == 0:
                return ToolResult(
                    ok=False,
                    output="[Nacht Code] old_string がファイル内に見つかりません（変更なし）",
                )
            if count > 1:
                return ToolResult(
                    ok=False,
                    output=(
                        f"[Nacht Code] old_string が{count}箇所に一致し一意でないため"
                        "変更しません（前後の文脈を含めて一意にしてください）"
                    ),
                )
            updated = original.replace(old_string, new_string, 1)
        else:
            updated = _strip_code_fences(content)
            if not updated.strip():
                return ToolResult(
                    ok=False,
                    output="[Nacht Code] content が空のため変更しません",
                )
        rel = str(path.relative_to(root))
        diff = _unified_diff(original, updated, rel)
        try:
            path.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return ToolResult(ok=False, output=f"[Nacht Code] 書き込み失敗: {exc}")
        _audit("edit_file", root, {"path": rel, "diff": diff[:_MAX_OUTPUT_CHARS]})
        return ToolResult(
            ok=True,
            output=f"編集しました: {rel}\n{diff[:_MAX_OUTPUT_CHARS]}",
            data={"dir": str(root), "path": rel, "diff": diff[:_MAX_OUTPUT_CHARS]},
        )

    def _create_file(self, root: Path, request: ToolRequest) -> ToolResult:
        path, error = _resolve_inside(root, request.params.get("path", ""))
        if error:
            return ToolResult(ok=False, output=f"[Nacht Code] {error}")
        if path.exists():
            return ToolResult(
                ok=False,
                output=(
                    f"[Nacht Code] 既にファイルが存在します: {path}"
                    "（上書きしません。編集は edit_file を使ってください）"
                ),
            )
        content = request.params.get("content", "")
        rel = str(path.relative_to(root))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(ok=False, output=f"[Nacht Code] 作成失敗: {exc}")
        diff = _unified_diff("", content, rel)
        _audit("create_file", root, {"path": rel, "diff": diff[:_MAX_OUTPUT_CHARS]})
        return ToolResult(
            ok=True,
            output=f"新規作成しました: {rel}（{len(content)}文字）",
            data={"dir": str(root), "path": rel, "diff": diff[:_MAX_OUTPUT_CHARS]},
        )

    def _delete_file(self, root: Path, request: ToolRequest) -> ToolResult:
        path, error = _resolve_inside(root, request.params.get("path", ""))
        if error:
            return ToolResult(ok=False, output=f"[Nacht Code] {error}")
        if not path.is_file():
            return ToolResult(
                ok=False, output=f"[Nacht Code] ファイルが存在しません: {path}"
            )
        rel = str(path.relative_to(root))
        try:
            preview = path.read_text(encoding="utf-8", errors="replace")[:1000]
        except OSError:
            preview = "（読み取り不可・バイナリ等）"
        try:
            path.unlink()
        except OSError as exc:
            return ToolResult(ok=False, output=f"[Nacht Code] 削除失敗: {exc}")
        _audit("delete_file", root, {"path": rel, "removed_preview": preview})
        return ToolResult(
            ok=True,
            output=f"ファイルを削除しました: {rel}",
            data={"dir": str(root), "path": rel},
        )

    def _delete_dir(self, root: Path, request: ToolRequest) -> ToolResult:
        # _resolve_inside は resolved == root を拒否するため、
        # 対象ディレクトリ自体はここに到達しない（安全弁）。
        path, error = _resolve_inside(root, request.params.get("path", ""))
        if error:
            return ToolResult(ok=False, output=f"[Nacht Code] {error}")
        if not path.is_dir():
            return ToolResult(
                ok=False, output=f"[Nacht Code] ディレクトリが存在しません: {path}"
            )
        rel = str(path.relative_to(root))
        entries = sum(1 for _ in path.rglob("*"))
        try:
            shutil.rmtree(path)
        except OSError as exc:
            return ToolResult(ok=False, output=f"[Nacht Code] 削除失敗: {exc}")
        _audit("delete_dir", root, {"path": rel, "entries_removed": entries})
        return ToolResult(
            ok=True,
            output=f"ディレクトリを削除しました: {rel}（{entries}エントリ）",
            data={"dir": str(root), "path": rel, "entries_removed": entries},
        )

    def _run_command(self, root: Path, request: ToolRequest) -> ToolResult:
        command = str(request.params.get("command") or "").strip()
        if not command:
            return ToolResult(
                ok=False,
                output='[Nacht Code] run_command には params {"command": ...} が必要です',
            )
        try:
            proc = subprocess.run(
                command, shell=True, cwd=str(root),
                capture_output=True, text=True, timeout=_COMMAND_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            _audit("run_command", root, {"command": command, "exit_code": "timeout"})
            return ToolResult(
                ok=False,
                output=f"[Nacht Code] コマンドが{_COMMAND_TIMEOUT_S}秒で完了しませんでした: {command}",
            )
        except OSError as exc:
            return ToolResult(ok=False, output=f"[Nacht Code] コマンド起動失敗: {exc}")
        output = (proc.stdout + proc.stderr)[-_MAX_OUTPUT_CHARS:]
        _audit("run_command", root, {"command": command, "exit_code": proc.returncode})
        return ToolResult(
            ok=proc.returncode == 0,
            output=f"$ {command}\nexit={proc.returncode}\n{output}",
            data={"dir": str(root), "command": command,
                  "exit_code": proc.returncode},
        )

    def _git_push(self, root: Path, request: ToolRequest) -> ToolResult:
        """git push。confirmed=True（人間の確認チャネル経由）以外では実行しない。"""
        if not (root / ".git").exists():
            return ToolResult(
                ok=False,
                output=f"[Nacht Code] git リポジトリではないため push できません: {root}",
            )

        def _git(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                ["git", *args], cwd=str(root), capture_output=True, text=True,
                timeout=_PUSH_TIMEOUT_S,
            )

        remote = str(request.params.get("remote") or "origin").strip()
        branch = str(request.params.get("branch") or "").strip()
        try:
            if not branch:
                branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            url_proc = _git("remote", "get-url", remote)
            if url_proc.returncode != 0:
                return ToolResult(
                    ok=False,
                    output=f"[Nacht Code] リモート '{remote}' が設定されていません",
                )
            url = url_proc.stdout.strip()
            ahead = _git("log", "--oneline", f"{remote}/{branch}..HEAD")
            commits = ahead.stdout.strip() if ahead.returncode == 0 \
                else _git("log", "--oneline", "-5").stdout.strip() + "\n（リモート追跡ブランチなし・直近5件を表示）"
        except (subprocess.TimeoutExpired, OSError) as exc:
            return ToolResult(ok=False, output=f"[Nacht Code] git 実行失敗: {exc}")

        if request.params.get("confirmed") is not True:
            # 確認前は絶対に push しない。プレビューだけを返す。
            return ToolResult(
                ok=True,
                output=(
                    "[確認待ち] push はまだ実行していません。\n"
                    f"remote : {remote}（{url}）\n"
                    f"branch : {branch}\n"
                    f"送信されるコミット:\n{commits or '（なし）'}"
                ),
                data={
                    "needs_confirmation": True, "dir": str(root),
                    "remote": remote, "branch": branch, "url": url,
                    "commits": commits[:_MAX_OUTPUT_CHARS],
                },
            )

        try:
            push = _git("push", remote, branch)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return ToolResult(ok=False, output=f"[Nacht Code] push 失敗: {exc}")
        if push.returncode != 0:
            return ToolResult(
                ok=False,
                output=f"[Nacht Code] push 失敗: {(push.stdout + push.stderr)[:800]}",
            )
        _audit("git_push", root, {
            "remote": remote, "url": url, "branch": branch,
            "commits": commits[:1000],
        })
        return ToolResult(
            ok=True,
            output=f"push しました: {remote}/{branch}（{url}）",
            data={"dir": str(root), "remote": remote, "branch": branch,
                  "url": url},
        )

    def _git_commit(self, root: Path, request: ToolRequest) -> ToolResult:
        if not (root / ".git").exists():
            return ToolResult(
                ok=False,
                output=f"[Nacht Code] git リポジトリではないため commit できません: {root}",
            )
        message = str(request.params.get("message") or "").strip() \
            or f"Nacht Code: {request.task_text[:60]}"

        def _git(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                ["git", *args], cwd=str(root), capture_output=True, text=True,
                timeout=_GIT_TIMEOUT_S,
            )

        try:
            add = _git("add", "-A")
            if add.returncode != 0:
                return ToolResult(
                    ok=False, output=f"[Nacht Code] git add 失敗: {add.stderr[:500]}"
                )
            commit = _git("commit", "-m", message)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return ToolResult(ok=False, output=f"[Nacht Code] git 実行失敗: {exc}")
        if commit.returncode != 0:
            return ToolResult(
                ok=False,
                output=(
                    "[Nacht Code] git commit 失敗（変更なしの可能性）: "
                    f"{(commit.stdout + commit.stderr)[:500]}"
                ),
            )
        head = _git("log", "--oneline", "-1").stdout.strip()
        _audit("git_commit", root, {"message": message, "head": head})
        return ToolResult(
            ok=True,
            output=f"コミットしました（push は git_push で確認の上実行）: {head}",
            data={"dir": str(root), "commit": head},
        )
