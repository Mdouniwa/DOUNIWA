"""モデルレジストリ。

model名 -> provider / endpoint / ポリシー のマッピングを一元管理する。
新しいモデルを追加する場合はここに ModelSpec を1つ足すだけでよい。
接続先の実体（URL・APIキー）は環境変数から解決するため、
このファイルには機密情報を書かない。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum


class Provider(str, Enum):
    """モデルの提供元。エンドポイント解決とフォールバック判定に使う。"""

    LOCAL_MLX = "local_mlx"      # M5 Max 上の MLX 系 OpenAI互換サーバー
    CLOUD_ANTHROPIC = "cloud_anthropic"
    CLOUD_GOOGLE = "cloud_google"


class ModelTier(str, Enum):
    """ルーティングポリシー用の階層。

    - WORKHORSE: 主力（31B〜35B級）。デフォルトはここから選ぶ。
    - QUALITY:   速度より品質が重要な時だけ使う（70B級）。
    - CLOUD:     ローカルで処理できない/明示指定時のみのフォールバック。
    """

    WORKHORSE = "workhorse"
    QUALITY = "quality"
    CLOUD = "cloud"


@dataclass(frozen=True)
class ModelSpec:
    """1モデル分の設定。

    endpoint_env / api_key_env は環境変数名であり、値そのものではない。
    """

    name: str                    # ルーティングに使う内部モデル名
    provider: Provider
    tier: ModelTier
    served_model_name: str       # エンドポイント側に渡す実モデル名
    endpoint_env: str            # base URL を持つ環境変数名
    api_key_env: str | None = None
    description: str = ""
    extra: dict = field(default_factory=dict)

    def resolve_endpoint(self) -> str | None:
        return os.environ.get(self.endpoint_env)

    def resolve_api_key(self) -> str | None:
        if self.api_key_env is None:
            return None
        return os.environ.get(self.api_key_env)


# --- モデルレジストリ本体 -------------------------------------------------
# ローカルモデルは同一の MLX サーバー（LOCAL_LLM_BASE_URL）に載る前提。
# モデルごとにサーバーを分ける場合は endpoint_env を分ければよい。

_REGISTRY: dict[str, ModelSpec] = {}


def _register(spec: ModelSpec) -> None:
    _REGISTRY[spec.name] = spec


_register(ModelSpec(
    name="gemma-31b",
    provider=Provider.LOCAL_MLX,
    tier=ModelTier.WORKHORSE,
    served_model_name=os.environ.get("GEMMA_SERVED_NAME", "gemma-3-27b-it-mlx"),
    endpoint_env="LOCAL_LLM_BASE_URL",
    api_key_env="LOCAL_LLM_API_KEY",
    description="主力その1。バランス型。日本語/要約/一般タスク向け。",
))

_register(ModelSpec(
    name="qwen-35b",
    provider=Provider.LOCAL_MLX,
    tier=ModelTier.WORKHORSE,
    served_model_name=os.environ.get("QWEN_SERVED_NAME", "qwen3-32b-mlx"),
    endpoint_env="LOCAL_LLM_BASE_URL",
    api_key_env="LOCAL_LLM_API_KEY",
    description="主力その2。コード/ツール呼び出し寄りのタスク向け。デフォルト。",
))

_register(ModelSpec(
    name="gemma-26b",
    provider=Provider.LOCAL_MLX,
    tier=ModelTier.WORKHORSE,
    served_model_name=os.environ.get(
        "GEMMA26B_SERVED_NAME", "mlx-community/gemma-4-26b-a4b-it-4bit"
    ),
    endpoint_env="LOCAL_LLM_BASE_URL",
    api_key_env="LOCAL_LLM_API_KEY",
    description="軽量枠。現在サーバー側は停止中のため、選択すると失敗しstubに落ちる。",
))

_register(ModelSpec(
    name="llama-70b",
    provider=Provider.LOCAL_MLX,
    tier=ModelTier.QUALITY,
    served_model_name=os.environ.get("LLAMA70B_SERVED_NAME", "llama-3.3-70b-mlx"),
    endpoint_env="LOCAL_LLM_BASE_URL",
    api_key_env="LOCAL_LLM_API_KEY",
    description="品質優先枠。速度より品質が重要な時だけ明示的に使う。",
))

_register(ModelSpec(
    name="cloud-claude",
    provider=Provider.CLOUD_ANTHROPIC,
    tier=ModelTier.CLOUD,
    served_model_name=os.environ.get("CLAUDE_SERVED_NAME", "claude-sonnet-4-5"),
    endpoint_env="ANTHROPIC_BASE_URL",
    api_key_env="ANTHROPIC_API_KEY",
    description="クラウドフォールバック。機微情報を含むタスクでは使わない。",
))

_register(ModelSpec(
    name="cloud-gemini",
    provider=Provider.CLOUD_GOOGLE,
    tier=ModelTier.CLOUD,
    served_model_name=os.environ.get("GEMINI_SERVED_NAME", "gemini-2.5-pro"),
    endpoint_env="GEMINI_BASE_URL",
    api_key_env="GEMINI_API_KEY",
    description="クラウドフォールバック。長文コンテキスト/調査系。",
))


DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "qwen-35b")


def get_model(name: str) -> ModelSpec:
    """モデル名から ModelSpec を引く。未登録なら KeyError。"""
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY))
        raise KeyError(f"unknown model '{name}'. registered: {known}")
    return _REGISTRY[name]


def list_models() -> list[ModelSpec]:
    return list(_REGISTRY.values())
