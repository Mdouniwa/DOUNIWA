"""モデルルーター。

「どのモデルで処理するか」の判断だけを担う。実際の呼び出しは client.py。

ルーティングの優先順位:
  1. ユーザーが --model で明示指定したもの
  2. タスク分類（TaskKind）に応じたポリシー
  3. デフォルトモデル（DEFAULT_MODEL 環境変数、既定 qwen-35b）

70B級（QUALITY tier）とクラウドは自動では選ばず、
明示指定またはポリシーで明確に要求された場合のみ使う。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.llm.models import DEFAULT_MODEL, ModelSpec, ModelTier, get_model
from app.orchestrator.classifier import TaskKind

logger = logging.getLogger(__name__)

# タスク種別 -> 推奨モデル名。
# ここを書き換えるだけでルーティング方針を変えられる。
_POLICY: dict[TaskKind, str] = {
    TaskKind.CODE: "qwen-35b",
    TaskKind.WRITE_NOTE: "gemma-31b",
    TaskKind.AUTOMATION: "qwen-35b",
    TaskKind.BROWSER: "qwen-35b",
    TaskKind.GENERAL: DEFAULT_MODEL,
}


@dataclass(frozen=True)
class RouteDecision:
    """ルーティング結果。ログ・デバッグ用に理由も残す。"""

    model: ModelSpec
    reason: str


class ModelRouter:
    def route(
        self,
        task_kind: TaskKind,
        explicit_model: str | None = None,
        quality_first: bool = False,
    ) -> RouteDecision:
        """モデルを決定する。

        Args:
            task_kind: 分類済みのタスク種別。
            explicit_model: CLI等で明示指定されたモデル名。最優先。
            quality_first: 速度より品質を優先するフラグ。QUALITY tier を選ぶ。
        """
        if explicit_model:
            spec = get_model(explicit_model)
            decision = RouteDecision(spec, f"明示指定 (--model {explicit_model})")
        elif quality_first:
            spec = get_model("llama-70b")
            decision = RouteDecision(spec, "品質優先フラグにより QUALITY tier を選択")
        else:
            name = _POLICY.get(task_kind, DEFAULT_MODEL)
            spec = get_model(name)
            decision = RouteDecision(spec, f"タスク種別 {task_kind.value} のポリシーにより選択")

        if decision.model.tier == ModelTier.CLOUD:
            logger.warning(
                "クラウドモデル %s を使用します。機微情報を含む入力でないことを確認してください。",
                decision.model.name,
            )
        logger.info("route: %s (%s)", decision.model.name, decision.reason)
        return decision
