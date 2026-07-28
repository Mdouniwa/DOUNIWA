"""Obsidian アダプタ（stub + 最小接続口）。

Obsidian vault はただのディレクトリなので、最小接続は
「vault 配下の Markdown を読み書きする」ことで成立する。
vault が未設定・存在しない場合は stub 応答。

対応 vault:
  - personal: OBSIDIAN_VAULT_PATH / OBSIDIAN_NOTE_FOLDER
  - akane   : OBSIDIAN_VAULT_AKANE_PATH / OBSIDIAN_NOTE_FOLDER_AKANE
  params の "vault"、またはタスク文中の「あかね」「akane」で akane 側を選ぶ。

安全方針:
  - save_note は新規作成のみ（既存ファイルは変更しない。衝突時は連番）
  - append_note は既存ノートへの追記のみ（存在しなければエラー。勝手に
    新規作成しない）。対象は vault 配下の .md に限定する。

将来拡張（docs/roadmap.md 参照）:
  - Mac mini 側 vault への書き込み（Syncthing/iCloud 経由 or REST プラグイン）
  - デイリーノート/テンプレート対応
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path

import httpx

from app.tools.base import ToolAdapter, ToolRequest, ToolResult

logger = logging.getLogger(__name__)

# 「『タイトル』というメモを保存して」形式からタイトルを拾う
_QUOTED_TITLE = re.compile(r"『([^』]+)』|「([^」]+)」")

_MAX_SEARCH_MATCHES = 10
_MAX_FILE_BYTES = 2 * 1024 * 1024  # 検索時に読む1ファイルの上限

# --- semantic_search（AIVENA OS /search を叩くだけ。索引はここでは作らない） ---
_SEMANTIC_TIMEOUT_S = 60.0
_SEMANTIC_DEFAULT_K = 5
_SEMANTIC_MAX_K = 20
#: この値未満は「関連性が低い可能性」の印を付ける（暫定値。除外はしない。
#: retriever にスコア閾値が無く常にk件返るため、表示側で注意を促す）
_SEMANTIC_LOW_SCORE = 0.35
#: kuro.console 側の vault 名 -> 索引側の vault 名。索引に無い名前は拒否する
_SEMANTIC_VAULT_MAP = {
    "personal": "Personal",
    "akane": "Akane",
    "あかね": "Akane",
}


def _title_from_task(task_text: str) -> str | None:
    m = _QUOTED_TITLE.search(task_text)
    if not m:
        return None
    return (m.group(1) or m.group(2) or "").strip() or None


def _iter_notes(root: Path):
    """vault 配下の .md を列挙する（.obsidian 等の隠しディレクトリは除外）。"""
    for path in sorted(root.rglob("*.md")):
        rel_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        yield path


class ObsidianAdapter(ToolAdapter):
    name = "obsidian"
    supported_actions = ("save_note", "search_notes", "semantic_search",
                         "append_note")
    action_docs = {
        "save_note": (
            "Obsidian vault に新規ノートを保存する。"
            ' params: {"title": "ノートのタイトル", "body": "本文",'
            ' "vault": "personal または akane"（省略時 personal）}'
        ),
        "search_notes": (
            "指定した語句がそのまま含まれるノートを探す（完全一致）。"
            "ファイル名・ID・固有の綴りを厳密に探す場合だけ使う。"
            "内容で探すときは semantic_search を使うこと。"
            ' params: {"query": "検索語", "vault": "personal または akane"}'
        ),
        "semantic_search": (
            "Obsidian vault を意味で検索する。表記が違っても内容が"
            "近ければ見つかる。ノートを探す場合はまずこれを使うこと。"
            ' params: {"query": "検索したい内容",'
            ' "vault": "personal または akane"（省略時は両vault横断）,'
            ' "k": 件数（省略時5）}'
        ),
        "append_note": (
            "既存ノートの末尾に追記する（存在しないノートには追記できない。"
            "新規作成は save_note を使う）。"
            ' params: {"path": "ノート名または相対パス", "body": "追記する本文",'
            ' "vault": "personal または akane"}'
        ),
    }
    write_actions = ("save_note", "append_note")

    def execute(self, request: ToolRequest) -> ToolResult:
        if request.action == "save_note":
            return self._save_note(request)
        if request.action == "search_notes":
            return self._search_notes(request)
        if request.action == "semantic_search":
            return self._semantic_search(request)
        if request.action == "append_note":
            return self._append_note(request)
        return ToolResult(ok=False, output=f"unknown action: {request.action}")

    # ------------------------------------------------------------------
    # vault 解決
    # ------------------------------------------------------------------

    @staticmethod
    def _vault_config(request: ToolRequest) -> tuple[str, str | None, str]:
        """(vault名, vaultパス, ノートフォルダ) を返す。

        params の "vault" 指定を最優先し、なければタスク文に
        「あかね」「akane」が含まれるかで判定する。
        """
        choice = str(request.params.get("vault") or "").strip().lower()
        text = (request.task_text or "").lower()
        wants_akane = choice in ("akane", "あかね") or (
            not choice and ("akane" in text or "あかね" in text)
        )
        if wants_akane:
            return (
                "akane",
                os.environ.get("OBSIDIAN_VAULT_AKANE_PATH"),
                os.environ.get("OBSIDIAN_NOTE_FOLDER_AKANE", "00_Inbox_akane"),
            )
        return (
            "personal",
            os.environ.get("OBSIDIAN_VAULT_PATH"),
            os.environ.get("OBSIDIAN_NOTE_FOLDER", "ai-workspace"),
        )

    @staticmethod
    def _vault_missing(label: str, action: str) -> ToolResult:
        env = ("OBSIDIAN_VAULT_AKANE_PATH" if label == "akane"
               else "OBSIDIAN_VAULT_PATH")
        return ToolResult(
            ok=True,
            stubbed=True,
            output=(
                f"[stub:obsidian] vault '{label}'（環境変数 {env}）が"
                f" 未設定または存在しないため stub 応答です。"
                f" '{action}' は実際には実行されていません。"
            ),
        )

    # ------------------------------------------------------------------
    # save_note
    # ------------------------------------------------------------------

    def _save_note(self, request: ToolRequest) -> ToolResult:
        label, vault, folder_name = self._vault_config(request)
        now = datetime.now()
        title = (
            request.params.get("title")
            or _title_from_task(request.task_text)
            or f"ai-workspace {now:%Y-%m-%d %H%M}"
        )
        body = request.params.get("body") or request.task_text

        if not vault or not Path(vault).is_dir():
            return self._vault_missing(label, f"save_note '{title}'")

        folder = Path(vault) / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        topic = "".join(c for c in title if c not in '\\/:*?"<>|').strip() or "note"
        path = folder / f"{now:%Y-%m-%d}_claude_{topic}.md"
        # 既存ノートは変更しない（新規作成のみ）。衝突時は連番を付ける。
        seq = 1
        while path.exists():
            seq += 1
            path = folder / f"{now:%Y-%m-%d}_claude_{topic}_{seq}.md"
        note = (
            "---\n"
            f"created: {now:%Y-%m-%dT%H:%M:%S}\n"
            "source: ai-workspace\n"
            f'title: "{title}"\n'
            "---\n\n"
            f"# {title}\n\n{body}\n"
        )
        try:
            path.write_text(note, encoding="utf-8")
            return ToolResult(
                ok=True,
                output=f"Obsidian ノートを保存しました（vault: {label}）: {path}",
                data={"path": str(path), "vault": label},
            )
        except OSError as exc:
            logger.warning("Obsidian ノート保存に失敗: %s", exc)
            return ToolResult(ok=False, output=f"ノート保存に失敗しました: {exc}")

    # ------------------------------------------------------------------
    # search_notes
    # ------------------------------------------------------------------

    def _search_notes(self, request: ToolRequest) -> ToolResult:
        label, vault, _ = self._vault_config(request)
        query = str(request.params.get("query") or "").strip()
        if not query:
            return ToolResult(
                ok=False,
                output='search_notes には params {"query": "検索語"} が必要です',
            )
        if not vault or not Path(vault).is_dir():
            return self._vault_missing(label, f"search_notes '{query}'")

        root = Path(vault)
        needle = query.lower()
        matches: list[dict] = []
        for path in _iter_notes(root):
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            pos = text.lower().find(needle)
            if pos == -1:
                continue
            line_no = text.count("\n", 0, pos) + 1
            line = text.splitlines()[line_no - 1].strip()
            matches.append({
                "path": str(path.relative_to(root)),
                "line": line_no,
                "snippet": line[:160],
            })
            if len(matches) >= _MAX_SEARCH_MATCHES:
                break

        if not matches:
            return ToolResult(
                ok=True,
                output=f"vault '{label}' 内に '{query}' を含むノートは見つかりませんでした。",
                data={"vault": label, "query": query, "matches": []},
            )
        lines = [f"vault '{label}' 内の検索結果（'{query}', {len(matches)}件"
                 f"{'・上限到達' if len(matches) >= _MAX_SEARCH_MATCHES else ''}）:"]
        for m in matches:
            lines.append(f"- {m['path']} (L{m['line']}): {m['snippet']}")
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={"vault": label, "query": query, "matches": matches},
        )

    # ------------------------------------------------------------------
    # semantic_search（AIVENA OS の /search を叩く薄いラッパー）
    # ------------------------------------------------------------------

    def _semantic_search(self, request: ToolRequest) -> ToolResult:
        query = str(request.params.get("query") or "").strip()
        if not query:
            return ToolResult(
                ok=False,
                output='semantic_search には params {"query": "検索したい内容"} が必要です',
            )

        url = os.environ.get("AIVENA_SEARCH_URL")
        token = os.environ.get("AIVENA_SEARCH_TOKEN")
        if not url or not token:
            missing = "AIVENA_SEARCH_URL" if not url else "AIVENA_SEARCH_TOKEN"
            return ToolResult(
                ok=True,
                stubbed=True,
                output=(
                    f"[stub:obsidian] {missing} が未設定のため stub 応答です。"
                    " 意味検索は実際には実行されていません。"
                ),
            )

        # vault 名の変換（索引側は Personal / Akane）。索引に無い名前は
        # 黙って0件にせず、対象外であることを明示して返す。
        vault_raw = str(request.params.get("vault") or "").strip()
        vault = None
        if vault_raw:
            vault = _SEMANTIC_VAULT_MAP.get(vault_raw.lower())
            if vault is None:
                known = " / ".join(sorted(set(_SEMANTIC_VAULT_MAP)))
                return ToolResult(
                    ok=False,
                    output=(
                        f"vault '{vault_raw}' は意味検索の索引対象外です"
                        f"（指定できるのは {known}。省略すると両vault横断）"
                    ),
                )

        try:
            k = int(request.params.get("k") or _SEMANTIC_DEFAULT_K)
        except (TypeError, ValueError):
            k = _SEMANTIC_DEFAULT_K
        k = max(1, min(k, _SEMANTIC_MAX_K))

        query_params = {"q": query, "k": k}
        if vault:
            query_params["vault"] = vault
        try:
            resp = httpx.get(
                url,
                params=query_params,
                headers={"X-AIVENA-TOKEN": token},
                timeout=_SEMANTIC_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            # 接続失敗・タイムアウト等。原因を隠すと診断できないため
            # 例外の型名と内容・接続先をそのまま返す。
            logger.warning("semantic_search の接続に失敗: %s", exc)
            return ToolResult(
                ok=False,
                output=(
                    "semantic_search の接続に失敗しました"
                    f"（{type(exc).__name__}: {exc} / 接続先: {url}）"
                ),
            )
        if resp.status_code != 200:
            # 401(認証)・422(空クエリ)・502(埋め込み失敗) 等を区別して返す
            return ToolResult(
                ok=False,
                output=(
                    f"semantic_search が HTTP {resp.status_code} を返しました:"
                    f" {resp.text[:300]}"
                ),
            )
        try:
            data = resp.json()
            results = data["results"]
        except (ValueError, KeyError) as exc:
            return ToolResult(
                ok=False,
                output=f"semantic_search の応答を解釈できません（{exc}）:"
                       f" {resp.text[:300]}",
            )

        scope = f"vault: {vault}" if vault else "両vault横断"
        if not results:
            return ToolResult(
                ok=True,
                output=(
                    f"意味検索の結果は0件でした（クエリ: '{query}' / {scope}）。"
                    "スコア閾値による除外はないため、0件は索引が空か"
                    " vault 絞り込みが原因です。"
                ),
                data={"query": query, "count": 0, "results": []},
            )

        lines = [
            "意味が近い順の候補です（類似度順に必ずk件返すため、"
            "無関係な結果が含まれることがあります）。"
            f" クエリ: '{query}' / {scope} / {len(results)}件:"
        ]
        for r in results:
            score = float(r.get("score") or 0.0)
            mark = "（関連性が低い可能性）" if score < _SEMANTIC_LOW_SCORE else ""
            snippet = str(r.get("text") or "").replace("\n", " ")[:160]
            lines.append(
                f"- [score {score:.3f}]{mark} {r.get('vault')}/{r.get('path')}:"
                f" {snippet}"
            )
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={"query": query, "count": len(results), "results": results},
        )

    # ------------------------------------------------------------------
    # append_note
    # ------------------------------------------------------------------

    def _append_note(self, request: ToolRequest) -> ToolResult:
        label, vault, _ = self._vault_config(request)
        target = str(
            request.params.get("path")
            or request.params.get("title")
            or _title_from_task(request.task_text)
            or ""
        ).strip()
        body = str(
            request.params.get("body") or request.params.get("text") or ""
        ).strip()
        if not target:
            return ToolResult(
                ok=False,
                output='append_note には params {"path": "ノート名または相対パス"} が必要です',
            )
        if not body:
            return ToolResult(
                ok=False,
                output='append_note には params {"body": "追記する本文"} が必要です',
            )
        if not vault or not Path(vault).is_dir():
            return self._vault_missing(label, f"append_note '{target}'")

        root = Path(vault)
        resolved = self._resolve_note(root, target)
        if isinstance(resolved, ToolResult):  # 解決失敗（エラーをそのまま返す）
            return resolved

        now = datetime.now()
        appended = f"\n\n---\n*追記 {now:%Y-%m-%d %H:%M} (ai-workspace)*\n\n{body}\n"
        try:
            with resolved.open("a", encoding="utf-8") as f:
                f.write(appended)
            return ToolResult(
                ok=True,
                output=f"既存ノートに追記しました（vault: {label}）: {resolved}",
                data={"path": str(resolved), "vault": label},
            )
        except OSError as exc:
            logger.warning("Obsidian ノート追記に失敗: %s", exc)
            return ToolResult(ok=False, output=f"ノート追記に失敗しました: {exc}")

    @staticmethod
    def _resolve_note(root: Path, target: str) -> Path | ToolResult:
        """追記対象ノートを特定する。見つからなければ ToolResult(ok=False)。

        新規作成は絶対にしない。相対パス完全一致 -> ファイル名部分一致の順で探す。
        """
        candidates = [root / target]
        if not target.endswith(".md"):
            candidates.append(root / f"{target}.md")
        for cand in candidates:
            try:
                cand.resolve().relative_to(root.resolve())
            except ValueError:
                return ToolResult(
                    ok=False,
                    output=f"vault 外のパスには追記できません: {target}",
                )
            if cand.is_file() and cand.suffix == ".md":
                return cand

        stem = target[:-3] if target.endswith(".md") else target
        hits = [p for p in _iter_notes(root) if stem.lower() in p.stem.lower()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            return ToolResult(
                ok=False,
                output=(
                    f"ノート '{target}' が見つからないため追記できません"
                    "（append_note は新規作成しません。新規なら save_note を使ってください）"
                ),
            )
        listing = ", ".join(str(p.relative_to(root)) for p in hits[:5])
        return ToolResult(
            ok=False,
            output=(
                f"ノート '{target}' の候補が{len(hits)}件あり特定できません: {listing}"
                "（params の path で相対パスを指定してください）"
            ),
        )
