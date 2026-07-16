"""実行計画のステップ実行エンジン。

設計原則（2026-07-16 の虚偽成功報告バグの再発防止）:
  - 各ステップの成功/失敗/stub/スキップを StepResult として個別に記録する。
    「計画があること」と「実行できたこと」を混同しない。
  - 失敗ポリシー: 失敗（またはスキップ）されたステップの出力に依存するステップ
    （params に {{stepN.output}} 参照を持つもの）はスキップし、
    独立したステップは続行する。
  - 実行時間の上限（MAX_PLAN_DURATION_SECONDS、既定300秒）を超えたら
    残りのステップをスキップして中断する。チェックはステップ間で行うため、
    実行中の1ステップ自体は中断しない（各ツールのHTTPタイムアウトが下限を守る）。
  - 進捗（各ステップの開始・終了）は logger と、EXECUTOR_LOG_DIR
    （既定 data/logs）配下のログファイルへ逐次書き込む。無人実行が途中で
    止まった場合に、どこまで進んだかを後から確認できるようにするため。
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.orchestrator.planner import Plan, PlanStep
from app.tools.base import ToolRequest, ToolResult
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_MAX_DURATION_S = 300.0
#: {{stepN.output}} 差し込み時の1出力あたり文字数上限（プロンプト肥大の防止）
MAX_EMBED_CHARS = 8000

_PLACEHOLDER = re.compile(r"\{\{step(\d+)\.output\}\}")

_file_logging_ready = False


def _ensure_file_logging() -> None:
    """executor の進捗をファイルにも書く。失敗しても実行は止めない。"""
    global _file_logging_ready
    if _file_logging_ready:
        return
    _file_logging_ready = True
    log_dir = Path(os.environ.get("EXECUTOR_LOG_DIR", "data/logs"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(
            log_dir / f"executor-{datetime.now():%Y-%m-%d}.log", encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    except OSError as exc:
        logger.warning("executor ログファイルを開けません（%s）。続行します。", exc)


def max_plan_duration_s() -> float:
    try:
        return float(
            os.environ.get("MAX_PLAN_DURATION_SECONDS", DEFAULT_MAX_DURATION_S)
        )
    except ValueError:
        return DEFAULT_MAX_DURATION_S


@dataclass
class StepResult:
    """1ステップ分の実行事実。最終応答はこのリストだけを根拠に生成される。"""

    index: int              # 1始まり
    tool: str
    action: str
    params: dict = field(default_factory=dict)
    ok: bool = False
    stubbed: bool = False
    output: str = ""
    skipped: bool = False
    skip_reason: str = ""
    duration_s: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.tool}.{self.action}"

    @property
    def status(self) -> str:
        if self.skipped:
            return f"スキップ（{self.skip_reason}）"
        if self.stubbed:
            return "stub（実接続なし・実際には実行されていない）"
        return "成功" if self.ok else "失敗"


def _referenced_steps(value) -> set[int]:
    """params 内の {{stepN.output}} が参照するステップ番号を集める。"""
    refs: set[int] = set()
    if isinstance(value, str):
        refs.update(int(n) for n in _PLACEHOLDER.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            refs |= _referenced_steps(v)
    elif isinstance(value, list):
        for v in value:
            refs |= _referenced_steps(v)
    return refs


def _substitute(value, outputs: dict[int, str]):
    """params 内の {{stepN.output}} を実際の出力で置き換える。"""
    if isinstance(value, str):
        return _PLACEHOLDER.sub(
            lambda m: outputs[int(m.group(1))][:MAX_EMBED_CHARS], value
        )
    if isinstance(value, dict):
        return {k: _substitute(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, outputs) for v in value]
    return value


def _run_single(
    registry: ToolRegistry, step: PlanStep, params: dict, task_text: str
) -> ToolResult:
    adapter = registry.get(step.tool)
    request = ToolRequest(action=step.action, params=params, task_text=task_text)
    error = adapter.validate(request)
    if error:
        return ToolResult(ok=False, output=error)
    try:
        return adapter.execute(request)
    except Exception as exc:  # ツール実装のバグで全体を落とさない
        logger.exception("tool '%s' の実行中に予期しないエラー", step.tool)
        return ToolResult(ok=False, output=f"tool '{step.tool}' 実行エラー: {exc}")


def execute_plan(
    plan: Plan,
    registry: ToolRegistry,
    task_text: str,
    extra_params: dict | None = None,
    max_duration_s: float | None = None,
) -> list[StepResult]:
    """計画のステップを順に実行し、全ステップ分の StepResult を返す。

    スキップされたステップも必ずリストに含める（実行されなかった事実を
    記録に残すため）。
    """
    _ensure_file_logging()
    budget = max_duration_s if max_duration_s is not None else max_plan_duration_s()
    total = len(plan.steps)
    start = time.monotonic()
    results: list[StepResult] = []

    logger.info("計画実行開始: %dステップ / タスク: %.100s", total, task_text)
    for i, step in enumerate(plan.steps, start=1):
        # CLI --param 等の共通パラメータ。計画側の指定が優先。
        params = {**(extra_params or {}), **step.params}

        elapsed = time.monotonic() - start
        if elapsed > budget:
            reason = f"実行時間上限({budget:.0f}秒)を超過したため未実行"
            results.append(StepResult(
                index=i, tool=step.tool, action=step.action, params=params,
                skipped=True, skip_reason=reason,
            ))
            logger.warning("step %d/%d %s -> スキップ: %s", i, total, step.label, reason)
            continue

        refs = _referenced_steps(params)
        invalid = sorted(n for n in refs if n < 1 or n >= i)
        if invalid:
            reason = f"不正なステップ参照 {{{{step{invalid[0]}.output}}}}（前のステップのみ参照可）"
            results.append(StepResult(
                index=i, tool=step.tool, action=step.action, params=params,
                skipped=True, skip_reason=reason,
            ))
            logger.warning("step %d/%d %s -> スキップ: %s", i, total, step.label, reason)
            continue

        blocked = sorted(
            n for n in refs if results[n - 1].skipped or not results[n - 1].ok
        )
        if blocked:
            reason = f"依存する step{blocked[0]} が失敗または未実行のため"
            results.append(StepResult(
                index=i, tool=step.tool, action=step.action, params=params,
                skipped=True, skip_reason=reason,
            ))
            logger.warning("step %d/%d %s -> スキップ: %s", i, total, step.label, reason)
            continue

        resolved = _substitute(params, {n: results[n - 1].output for n in refs})
        logger.info("step %d/%d 開始: %s", i, total, step.label)
        t0 = time.monotonic()
        result = _run_single(registry, step, resolved, task_text)
        duration = time.monotonic() - t0
        record = StepResult(
            index=i, tool=step.tool, action=step.action, params=resolved,
            ok=result.ok, stubbed=result.stubbed, output=result.output,
            duration_s=duration,
        )
        results.append(record)
        logger.info(
            "step %d/%d 終了: %s -> %s (%.1f秒)",
            i, total, step.label, record.status, duration,
        )

    logger.info(
        "計画実行終了: 成功%d / 失敗%d / スキップ%d",
        sum(1 for r in results if not r.skipped and r.ok),
        sum(1 for r in results if not r.skipped and not r.ok),
        sum(1 for r in results if r.skipped),
    )
    return results
