"""LLMClient の content 欠落リトライの検証。

reasoning 系モデルが思考でトークンを使い切ると応答に content が
含まれない。1回だけリトライし、それでも欠落なら stub に落ちること。
"""

from __future__ import annotations

import httpx

from app.llm.client import ChatMessage, LLMClient
from app.llm.models import get_model


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


def _payload_without_content() -> dict:
    return {"choices": [{"message": {"role": "assistant", "reasoning": "…"},
                         "finish_reason": "length"}]}


def _payload_with_content(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}]}


def _setup(monkeypatch, responses: list[dict]) -> list[int]:
    calls: list[int] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(1)
        return _FakeResponse(responses[len(calls) - 1])

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://fake:1/v1")
    return calls


def test_retry_once_when_content_missing_then_succeeds(monkeypatch):
    calls = _setup(monkeypatch, [
        _payload_without_content(),
        _payload_with_content("2回目で成功"),
    ])
    result = LLMClient().chat(get_model("qwen-35b"), [ChatMessage("user", "hi")])
    assert len(calls) == 2
    assert result.stubbed is False
    assert result.content == "2回目で成功"


def test_stub_fallback_when_content_missing_twice(monkeypatch):
    calls = _setup(monkeypatch, [
        _payload_without_content(),
        _payload_without_content(),
    ])
    result = LLMClient().chat(get_model("qwen-35b"), [ChatMessage("user", "hi")])
    assert len(calls) == 2
    assert result.stubbed is True
    assert "content" in result.note  # stub の理由が note に残る


def test_no_retry_on_connection_error(monkeypatch):
    calls: list[int] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(1)
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://fake:1/v1")
    result = LLMClient().chat(get_model("qwen-35b"), [ChatMessage("user", "hi")])
    assert len(calls) == 1  # 接続エラーはリトライしない
    assert result.stubbed is True
    assert "ConnectError" in result.note  # 例外の型名が note に残る


def test_stub_note_when_endpoint_unset(monkeypatch):
    monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
    result = LLMClient().chat(get_model("qwen-35b"), [ChatMessage("user", "hi")])
    assert result.stubbed is True
    assert "LOCAL_LLM_BASE_URL" in result.note  # 未設定の環境変数名が note に残る


# --- 思考モード抑制（chat_template_kwargs）とタイムアウト設定 ---------------


def _capture_payload(monkeypatch) -> dict:
    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["payload"] = json
        captured["timeout"] = timeout
        return _FakeResponse(_payload_with_content("ok"))

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://fake:1/v1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://fake:2/v1")
    return captured


def test_local_qwen_payload_disables_thinking(monkeypatch):
    captured = _capture_payload(monkeypatch)
    monkeypatch.delenv("QWEN_DISABLE_THINKING", raising=False)  # デフォルト有効
    LLMClient().chat(get_model("qwen-35b"), [ChatMessage("user", "hi")])
    assert captured["payload"]["chat_template_kwargs"] == {
        "enable_thinking": False
    }


def test_cloud_payload_has_no_chat_template_kwargs(monkeypatch):
    captured = _capture_payload(monkeypatch)
    LLMClient().chat(get_model("cloud-claude"), [ChatMessage("user", "hi")])
    assert "chat_template_kwargs" not in captured["payload"]


def test_thinking_suppression_can_be_disabled_by_env(monkeypatch):
    captured = _capture_payload(monkeypatch)
    monkeypatch.setenv("QWEN_DISABLE_THINKING", "0")
    LLMClient().chat(get_model("qwen-35b"), [ChatMessage("user", "hi")])
    assert "chat_template_kwargs" not in captured["payload"]


def test_timeout_default_is_180(monkeypatch):
    captured = _capture_payload(monkeypatch)
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    LLMClient().chat(get_model("qwen-35b"), [ChatMessage("user", "hi")])
    assert captured["timeout"] == 180.0


def test_timeout_overridable_by_env(monkeypatch):
    captured = _capture_payload(monkeypatch)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")
    LLMClient().chat(get_model("qwen-35b"), [ChatMessage("user", "hi")])
    assert captured["timeout"] == 45.0
