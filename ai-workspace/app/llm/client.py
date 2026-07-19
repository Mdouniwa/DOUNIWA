"""OpenAI互換 chat completions クライアント。

MLX 系ローカルサーバー（mlx_lm.server / LM Studio 等）も
クラウドプロキシも、OpenAI互換の /chat/completions として同じ経路で叩く。

エンドポイントが未設定・到達不能な場合は stub 応答にフォールバックするため、
LLMサーバーが無い環境でも end-to-end の一本線が動く。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.llm.models import ModelSpec

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 120.0

# mlx_lm.server は max_tokens 未指定だと 512 で打ち切る。
# reasoning 系モデル（Qwen3.6 等）は思考だけで 512 を超え、
# content が欠落して stub フォールバックしてしまうため、明示的に広げる。
DEFAULT_MAX_TOKENS = 4096


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class ChatResult:
    model_name: str          # 内部モデル名（ルーティング名）
    content: str
    stubbed: bool            # True なら実LLMを呼ばず stub 応答
    raw: dict | None = None  # デバッグ用の生レスポンス


class LLMClient:
    """ModelSpec を受けて OpenAI互換エンドポイントを呼ぶ薄いラッパー。"""

    def __init__(self, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s

    def chat(
        self,
        model: ModelSpec,
        messages: list[ChatMessage],
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ChatResult:
        base_url = model.resolve_endpoint()
        if not base_url:
            logger.warning(
                "モデル %s のエンドポイント（環境変数 %s）が未設定のため stub 応答を返します。",
                model.name, model.endpoint_env,
            )
            return self._stub_result(model, messages)

        headers = {"Content-Type": "application/json"}
        api_key = model.resolve_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model.served_model_name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
        }

        url = base_url.rstrip("/") + "/chat/completions"
        for attempt in (1, 2):
            try:
                resp = httpx.post(url, json=payload, headers=headers,
                                  timeout=self._timeout_s)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if content is None:
                    raise KeyError("content is null")
                return ChatResult(model_name=model.name, content=content,
                                  stubbed=False, raw=data)
            except (KeyError, ValueError) as exc:
                # reasoning 系モデルが思考でトークンを使い切ると content が
                # 欠落する。サンプリングの揺らぎで抜けることがあるため
                # 1回だけリトライする。
                if attempt == 1:
                    logger.warning(
                        "モデル %s の応答に content がありません（%s）。リトライします。",
                        model.name, exc,
                    )
                    continue
                logger.warning(
                    "モデル %s の呼び出しに失敗（%s）。stub 応答にフォールバックします。",
                    model.name, exc,
                )
                return self._stub_result(model, messages)
            except httpx.HTTPError as exc:
                # 接続系の失敗はリトライしない（サーバー停止時に待ち時間を倍にしない）
                logger.warning(
                    "モデル %s の呼び出しに失敗（%s）。stub 応答にフォールバックします。",
                    model.name, exc,
                )
                return self._stub_result(model, messages)
        return self._stub_result(model, messages)  # 到達しない（型の整合用）

    @staticmethod
    def _stub_result(model: ModelSpec, messages: list[ChatMessage]) -> ChatResult:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        content = (
            f"[stub:{model.name}] 実LLM未接続のためダミー応答です。"
            f" 受理した指示: {last_user[:200]}"
        )
        return ChatResult(model_name=model.name, content=content, stubbed=True)
