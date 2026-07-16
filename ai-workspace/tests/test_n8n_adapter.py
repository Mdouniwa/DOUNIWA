"""N8nAdapter list_workflows の検証（httpx はモック）。"""

from __future__ import annotations

import httpx

from app.tools.base import ToolRequest
from app.tools.n8n.adapter import N8nAdapter


def _request() -> ToolRequest:
    return ToolRequest(action="list_workflows", params={},
                       task_text="n8nのワークフロー一覧を見せて")


def test_list_workflows_stub_when_api_key_unset(monkeypatch):
    monkeypatch.setenv("N8N_API_BASE_URL", "http://fake:5678/api/v1")
    monkeypatch.delenv("N8N_API_KEY", raising=False)
    result = N8nAdapter().execute(_request())
    assert result.ok is True
    assert result.stubbed is True
    assert "実際には取得していません" in result.output


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_list_workflows_formats_names_and_active(monkeypatch):
    monkeypatch.setenv("N8N_API_BASE_URL", "http://fake:5678/api/v1")
    monkeypatch.setenv("N8N_API_KEY", "key")
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse({"data": [
            {"id": "1", "name": "毎朝の要約", "active": True},
            {"id": "2", "name": "テスト配線", "active": False},
        ]})

    monkeypatch.setattr(httpx, "get", fake_get)
    result = N8nAdapter().execute(_request())

    assert result.ok is True
    assert result.stubbed is False
    assert captured["url"] == "http://fake:5678/api/v1/workflows"
    assert captured["headers"]["X-N8N-API-KEY"] == "key"
    assert "毎朝の要約 [有効]" in result.output
    assert "テスト配線 [無効]" in result.output
    assert result.data["count"] == 2


def test_list_workflows_reports_http_error_honestly(monkeypatch):
    monkeypatch.setenv("N8N_API_BASE_URL", "http://fake:5678/api/v1")
    monkeypatch.setenv("N8N_API_KEY", "key")

    def fake_get(url, headers=None, timeout=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", fake_get)
    result = N8nAdapter().execute(_request())
    assert result.ok is False
    assert "取得に失敗しました" in result.output
