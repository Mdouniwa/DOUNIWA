"""browser ツールの検証（Fake backend 注入・Playwright 不要）。

特に安全系を厚く:
  - read: 外部データマーク包み / 許可ドメインのみ
  - ドメイン境界: 未知ドメイン拒否 / セッション承認 / リダイレクト停止
  - 承認ゲート: 承認なし write 不可 / confirmed＋トークン一致で実行 /
    承認フラグのLLM由来注入（planner・executor 経由）が迂回不可
  - allowlist追記: 人間チャネル経由のみ / LLM由来 persist_domain では不可
  - 隔離層3: browser ステップ間の {{stepN.output}} 差し込みはスキップ
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.orchestrator.executor import execute_plan
from app.orchestrator.planner import Plan, PlanStep, _parse_steps
from app.tools.base import ToolRequest
from app.tools.browser.adapter import (
    EXTERNAL_BEGIN,
    EXTERNAL_END,
    HUMAN_ONLY_PARAM_KEYS,
    BrowserAdapter,
    BrowserBackend,
    PageHandle,
    add_domain_to_allowlist,
    clear_session_approvals,
    clear_write_tokens,
    load_allowed_domains,
)
from app.tools.browser.runner import handle_browser_confirmation
from app.tools.registry import ToolRegistry


class FakePage(PageHandle):
    """開いたページの偽物。write 操作は backend.actions に記録するだけ。"""

    def __init__(self, url: str, backend: "FakeBackend") -> None:
        self._url = url
        self._backend = backend

    @property
    def final_url(self) -> str:
        return self._backend.redirects.get(self._url, self._url)

    def title(self) -> str:
        return "Fake Title"

    def text(self) -> str:
        return "偽のページ本文"

    def links(self) -> list[tuple[str, str]]:
        return [("リンク", "https://example.com/next")]

    def elements(self, selector: str) -> list[str]:
        return [f"element-of-{selector}"]

    def screenshot(self, path: str) -> None:
        pass

    def click(self, selector: str) -> None:
        self._backend.actions.append(("click", selector))
        nav = self._backend.nav_on_click.get(selector)
        if nav:
            self._backend.redirects[self._url] = nav

    def fill(self, selector: str, value: str) -> None:
        self._backend.actions.append(("fill", selector, value))


class FakeBackend(BrowserBackend):
    def __init__(self, redirects: dict | None = None,
                 nav_on_click: dict | None = None) -> None:
        self.redirects = dict(redirects or {})   # 開いたURL -> 最終URL
        self.nav_on_click = dict(nav_on_click or {})  # selector -> 遷移先
        self.opened: list[str] = []
        self.actions: list[tuple] = []

    @contextmanager
    def open(self, url: str):
        self.opened.append(url)
        yield FakePage(url, self)


@pytest.fixture
def allowlist(tmp_path, monkeypatch):
    """テスト専用 allowlist（example.com のみ許可）。本物には触れない。"""
    path = tmp_path / "browser_allowlist.json"
    path.write_text(
        json.dumps({"allowed_domains": ["example.com"]}), encoding="utf-8"
    )
    monkeypatch.setenv("BROWSER_ALLOWLIST_PATH", str(path))
    monkeypatch.setenv("EXECUTOR_LOG_DIR", str(tmp_path / "logs"))
    clear_session_approvals()
    clear_write_tokens()
    yield path
    clear_session_approvals()
    clear_write_tokens()


def _req(action: str, **params) -> ToolRequest:
    return ToolRequest(action=action, params=params, task_text="テスト")


def _registry(adapter: BrowserAdapter) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(adapter)
    return registry


def _preview_token(adapter: BrowserAdapter, action: str, **params) -> str:
    """正規手順のプレビューを踏んでワンタイムトークンを得る。"""
    result = adapter.execute(_req(action, **params))
    assert result.data.get("needs_confirmation") and result.data["kind"] == "write"
    return result.data["confirm_token"]


# ----------------------------------------------------------------------
# read: 外部データマーク・許可ドメイン
# ----------------------------------------------------------------------

def test_fetch_page_is_wrapped_in_external_marks(allowlist):
    backend = FakeBackend()
    result = BrowserAdapter(backend=backend).execute(
        _req("fetch_page", url="https://example.com/page"))
    assert result.ok
    assert result.output.startswith(EXTERNAL_BEGIN)
    assert result.output.endswith(EXTERNAL_END)
    assert "偽のページ本文" in result.output
    assert result.data["external"] is True


def test_subdomain_of_allowed_domain_is_allowed(allowlist):
    backend = FakeBackend()
    result = BrowserAdapter(backend=backend).execute(
        _req("fetch_page", url="https://docs.example.com/page"))
    assert result.ok and backend.opened == ["https://docs.example.com/page"]


def test_non_http_scheme_is_rejected(allowlist):
    backend = FakeBackend()
    result = BrowserAdapter(backend=backend).execute(
        _req("fetch_page", url="file:///etc/passwd"))
    assert result.ok is False
    assert backend.opened == []


# ----------------------------------------------------------------------
# ドメイン境界
# ----------------------------------------------------------------------

def test_unknown_domain_needs_confirmation_and_is_not_opened(allowlist):
    backend = FakeBackend()
    result = BrowserAdapter(backend=backend).execute(
        _req("fetch_page", url="https://unknown.example.org/x"))
    assert result.data.get("needs_confirmation") is True
    assert result.data["kind"] == "domain"
    assert result.data["domain"] == "unknown.example.org"
    assert backend.opened == []           # ページを開いていない
    assert "偽のページ本文" not in result.output


def test_domain_approved_grants_session_access(allowlist):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    # 人間チャネルが domain_approved=True で呼び直す
    result = adapter.execute(_req(
        "fetch_page", url="https://unknown.example.org/x",
        domain_approved=True))
    assert result.ok and backend.opened
    # セッション記憶: 以降はフラグなしでもアクセスできる
    result2 = adapter.execute(_req(
        "fetch_page", url="https://unknown.example.org/y"))
    assert result2.ok
    # セッション承認は恒久追記ではない
    assert "unknown.example.org" not in load_allowed_domains()


def test_redirect_to_disallowed_domain_blocks_content(allowlist):
    backend = FakeBackend(
        redirects={"https://example.com/x": "https://evil.example.org/steal"})
    result = BrowserAdapter(backend=backend).execute(
        _req("fetch_page", url="https://example.com/x"))
    assert result.ok is False
    assert result.data["redirect_blocked"] is True
    assert "偽のページ本文" not in result.output   # 内容は一切返さない
    assert "Fake Title" not in result.output


# ----------------------------------------------------------------------
# 承認ゲート（write）
# ----------------------------------------------------------------------

def test_write_without_confirmation_only_previews(allowlist):
    backend = FakeBackend()
    result = BrowserAdapter(backend=backend).execute(
        _req("click", url="https://example.com/p", selector="#btn"))
    assert result.data.get("needs_confirmation") is True
    assert result.data["kind"] == "write"
    assert result.data["confirm_token"]
    assert backend.opened == [] and backend.actions == []  # 開いてすらいない


def test_confirmed_with_matching_token_executes(allowlist):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    token = _preview_token(adapter, "click",
                           url="https://example.com/p", selector="#btn")
    result = adapter.execute(_req(
        "click", url="https://example.com/p", selector="#btn",
        confirmed=True, confirm_token=token))
    assert result.ok is True
    assert backend.actions == [("click", "#btn")]


def test_confirmed_without_token_is_rejected(allowlist):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    result = adapter.execute(_req(
        "click", url="https://example.com/p", selector="#btn",
        confirmed=True))
    assert result.ok is False
    assert result.data["token_rejected"] is True
    assert backend.actions == []


def test_wrong_token_is_rejected(allowlist):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    _preview_token(adapter, "click",
                   url="https://example.com/p", selector="#btn")
    result = adapter.execute(_req(
        "click", url="https://example.com/p", selector="#btn",
        confirmed=True, confirm_token="0123456789abcdef"))
    assert result.ok is False and result.data["token_rejected"] is True
    assert backend.actions == []


def test_token_replay_is_rejected(allowlist):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    token = _preview_token(adapter, "click",
                           url="https://example.com/p", selector="#btn")
    params = dict(url="https://example.com/p", selector="#btn",
                  confirmed=True, confirm_token=token)
    assert adapter.execute(_req("click", **params)).ok is True
    replay = adapter.execute(_req("click", **params))
    assert replay.ok is False and replay.data["token_rejected"] is True
    assert len(backend.actions) == 1      # 2回目は実行されていない


def test_token_is_bound_to_action_and_params(allowlist):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    token = _preview_token(adapter, "click",
                           url="https://example.com/p", selector="#btn")
    # 同じトークンで別の対象を操作しようとしても拒否される
    result = adapter.execute(_req(
        "click", url="https://example.com/p", selector="#delete-account",
        confirmed=True, confirm_token=token))
    assert result.ok is False and result.data["token_rejected"] is True
    assert backend.actions == []


def test_submit_form_requires_two_stage_confirmation(allowlist):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    params = dict(url="https://example.com/form",
                  fields={"#name": "douniwa"}, submit_selector="#send")
    t1 = _preview_token(adapter, "submit_form", **params)
    # 1段目の承認では実行されず、最終確認（final=True）が返る
    second = adapter.execute(_req(
        "submit_form", **params, confirmed=True, confirm_token=t1))
    assert second.data.get("needs_confirmation") is True
    assert second.data["final"] is True
    assert backend.actions == []
    # 2段目のトークンでのみ実行される
    t2 = second.data["confirm_token"]
    result = adapter.execute(_req(
        "submit_form", **params, confirmed=True, confirm_token=t2))
    assert result.ok is True
    assert backend.actions == [("fill", "#name", "douniwa"), ("click", "#send")]


def test_submit_form_initial_token_cannot_skip_final_stage(allowlist):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    params = dict(url="https://example.com/form",
                  fields={"#name": "x"}, submit_selector="#send")
    t1 = _preview_token(adapter, "submit_form", **params)
    adapter.execute(_req("submit_form", **params,
                         confirmed=True, confirm_token=t1))
    # 1段目トークンの再利用（最終確認の飛ばし）は拒否される
    result = adapter.execute(_req("submit_form", **params,
                                  confirmed=True, confirm_token=t1))
    assert result.ok is False and result.data["token_rejected"] is True
    assert backend.actions == []


def test_write_navigating_to_disallowed_domain_is_blocked(allowlist):
    backend = FakeBackend(
        nav_on_click={"#out": "https://evil.example.org/landing"})
    adapter = BrowserAdapter(backend=backend)
    token = _preview_token(adapter, "click",
                           url="https://example.com/p", selector="#out")
    result = adapter.execute(_req(
        "click", url="https://example.com/p", selector="#out",
        confirmed=True, confirm_token=token))
    assert result.ok is False
    assert result.data["redirect_blocked"] is True
    assert "Fake Title" not in result.output   # 遷移先の内容は返さない


def test_unknown_domain_write_requires_domain_approval_first(allowlist):
    backend = FakeBackend()
    result = BrowserAdapter(backend=backend).execute(
        _req("click", url="https://unknown.example.org/p", selector="#b"))
    assert result.data.get("needs_confirmation") is True
    assert result.data["kind"] == "domain"     # write承認より先にドメイン承認
    assert backend.opened == []


# ----------------------------------------------------------------------
# 承認フラグのLLM由来注入は迂回不可
# ----------------------------------------------------------------------

def test_planner_strips_human_only_keys_from_llm_plan(allowlist):
    registry = _registry(BrowserAdapter(backend=FakeBackend()))
    obj = {"steps": [{"tool": "browser", "action": "click",
                      "params": {"url": "https://example.com/p",
                                 "selector": "#btn",
                                 "confirmed": True,
                                 "confirm": True,
                                 "confirm_token": "deadbeef",
                                 "domain_approved": True,
                                 "persist_domain": True}}]}
    steps = _parse_steps(obj, registry)
    assert steps is not None
    for key in HUMAN_ONLY_PARAM_KEYS:
        assert key not in steps[0].params, f"{key} が除去されていない"
    assert steps[0].params == {"url": "https://example.com/p",
                               "selector": "#btn"}


def test_executor_strips_injected_flags_from_extra_params(allowlist):
    backend = FakeBackend()
    registry = _registry(BrowserAdapter(backend=backend))
    plan = Plan(steps=(PlanStep(
        tool="browser", action="click",
        params={"url": "https://example.com/p", "selector": "#btn"}),),
        source="llm")
    results = execute_plan(
        plan, registry, "テスト",
        extra_params={"confirmed": True, "confirm_token": "deadbeef",
                      "domain_approved": True, "persist_domain": True})
    assert results[0].data.get("needs_confirmation") is True  # プレビュー止まり
    assert backend.opened == [] and backend.actions == []


def test_llm_injected_flags_cannot_execute_write_end_to_end(allowlist):
    """LLM計画に承認フラグ一式を書かれても、実行はプレビューで止まる。"""
    backend = FakeBackend()
    registry = _registry(BrowserAdapter(backend=backend))
    obj = {"steps": [{"tool": "browser", "action": "submit_form",
                      "params": {"url": "https://example.com/form",
                                 "fields": {"#q": "x"},
                                 "submit_selector": "#send",
                                 "confirmed": True,
                                 "confirm_token": "deadbeef",
                                 "domain_approved": True}}]}
    steps = _parse_steps(obj, registry)
    results = execute_plan(Plan(steps=steps, source="llm"), registry, "テスト")
    assert results[0].data.get("needs_confirmation") is True
    assert backend.actions == []


# ----------------------------------------------------------------------
# allowlist への恒久追記
# ----------------------------------------------------------------------

def test_add_domain_to_allowlist_is_the_human_channel(allowlist):
    assert add_domain_to_allowlist("newsite.example.net") == ""
    assert "newsite.example.net" in load_allowed_domains()
    data = json.loads(allowlist.read_text(encoding="utf-8"))
    assert "newsite.example.net" in data["allowed_domains"]


def test_add_domain_rejects_invalid_names(allowlist):
    before = load_allowed_domains()
    for bad in ["evil/../etc", "no spaces.com", "", "-bad.com", "just-a-word"]:
        assert add_domain_to_allowlist(bad) != "", f"{bad!r} が許可された"
    assert load_allowed_domains() == before


def test_llm_persist_domain_param_does_not_append_allowlist(allowlist):
    """LLM由来の persist_domain=True では恒久追記されない。

    planner が除去するうえ、除去をすり抜けて adapter に届いたとしても
    adapter は persist_domain を追記の引き金として一切参照しない。
    """
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    before = load_allowed_domains()
    result = adapter.execute(_req(
        "fetch_page", url="https://unknown.example.org/x",
        persist_domain=True))
    assert result.data.get("needs_confirmation") is True
    assert load_allowed_domains() == before
    # domain_approved（セッション承認）と併用されても恒久追記はされない
    adapter.execute(_req(
        "fetch_page", url="https://unknown.example.org/x",
        domain_approved=True, persist_domain=True))
    assert load_allowed_domains() == before


# ----------------------------------------------------------------------
# 隔離層3: browser 出力を browser ステップへ差し込めない
# ----------------------------------------------------------------------

def test_browser_output_cannot_feed_another_browser_step(allowlist):
    backend = FakeBackend()
    registry = _registry(BrowserAdapter(backend=backend))
    plan = Plan(steps=(
        PlanStep(tool="browser", action="fetch_page",
                 params={"url": "https://example.com/a"}),
        PlanStep(tool="browser", action="click",
                 params={"url": "https://example.com/b",
                         "selector": "{{step1.output}}"}),
    ), source="llm")
    results = execute_plan(plan, registry, "テスト")
    assert results[0].ok is True
    assert results[1].skipped is True
    assert "インジェクション隔離" in results[1].skip_reason
    assert backend.opened == ["https://example.com/a"]  # step2 は開いていない


# ----------------------------------------------------------------------
# CLI 承認チャネル（runner.py）
# ----------------------------------------------------------------------

def _asker(*answers):
    it = iter(answers)
    return lambda _prompt: next(it)


def _domain_confirmation(adapter):
    result = adapter.execute(_req(
        "click", url="https://newsite.example.net/p", selector="#go"))
    assert result.data["kind"] == "domain"
    return result.data


def test_cli_domain_deny_aborts(allowlist, capsys):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    result = handle_browser_confirmation(
        _domain_confirmation(adapter), adapter=adapter, ask=_asker("n"))
    assert result is None
    assert backend.opened == [] and backend.actions == []
    assert "中止" in capsys.readouterr().out


def test_cli_domain_once_then_write_confirm_executes(allowlist):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    result = handle_browser_confirmation(
        _domain_confirmation(adapter), adapter=adapter, ask=_asker("y", "y"))
    assert result is not None and result.ok is True
    assert backend.actions == [("click", "#go")]
    # y（今回だけ）は恒久追記しない
    assert "newsite.example.net" not in load_allowed_domains()


def test_cli_domain_persist_appends_allowlist(allowlist):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    result = handle_browser_confirmation(
        _domain_confirmation(adapter), adapter=adapter,
        ask=_asker("p", "n"))   # 恒久承認 → write確認は拒否
    assert result is None
    assert "newsite.example.net" in load_allowed_domains()
    assert backend.actions == []   # write は拒否したので実行されていない


def test_cli_write_deny_aborts(allowlist):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    preview = adapter.execute(_req(
        "click", url="https://example.com/p", selector="#btn"))
    result = handle_browser_confirmation(
        preview.data, adapter=adapter, ask=_asker("n"))
    assert result is None and backend.actions == []


def test_cli_submit_form_asks_twice(allowlist):
    backend = FakeBackend()
    adapter = BrowserAdapter(backend=backend)
    preview = adapter.execute(_req(
        "submit_form", url="https://example.com/form",
        fields={"#q": "hello"}, submit_selector="#send"))
    # 初回承認だけで最終確認を拒否したら実行されない
    result = handle_browser_confirmation(
        preview.data, adapter=adapter, ask=_asker("y", "n"))
    assert result is None and backend.actions == []
    # 両方 y なら実行される
    preview2 = adapter.execute(_req(
        "submit_form", url="https://example.com/form",
        fields={"#q": "hello"}, submit_selector="#send"))
    result2 = handle_browser_confirmation(
        preview2.data, adapter=adapter, ask=_asker("y", "y"))
    assert result2 is not None and result2.ok is True
    assert backend.actions == [("fill", "#q", "hello"), ("click", "#send")]


# ----------------------------------------------------------------------
# UI 承認チャネル（/api/browser/confirm）
# ----------------------------------------------------------------------

@pytest.fixture
def api(allowlist, monkeypatch):
    """TestClient と Fake backend。エンドポイント内の BrowserAdapter() が
    Fake を使うよう _default_backend を差し替える（実 Playwright 不使用）。"""
    import app.server.main as server_main
    from app.tools.browser import adapter as adapter_module

    backend = FakeBackend()
    monkeypatch.setattr(adapter_module, "_default_backend", lambda: backend)
    return TestClient(server_main.app), backend


def test_api_write_with_smuggled_flags_is_rejected(api, allowlist):
    client, backend = api
    res = client.post("/api/browser/confirm", json={
        "kind": "write", "action": "click",
        "params": {"url": "https://example.com/p", "selector": "#btn",
                   "confirmed": True, "confirm_token": "smuggled",
                   "domain_approved": True, "persist_domain": True}})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["data"]["token_rejected"] is True
    assert backend.actions == []


def test_api_write_with_valid_token_executes(api, allowlist):
    client, backend = api
    adapter = BrowserAdapter(backend=backend)
    token = _preview_token(adapter, "click",
                           url="https://example.com/p", selector="#btn")
    res = client.post("/api/browser/confirm", json={
        "kind": "write", "action": "click",
        "params": {"url": "https://example.com/p", "selector": "#btn"},
        "confirm_token": token})
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert backend.actions == [("click", "#btn")]


def test_api_domain_once_does_not_persist(api, allowlist):
    client, backend = api
    res = client.post("/api/browser/confirm", json={
        "kind": "domain", "action": "fetch_page",
        "params": {"url": "https://newsite.example.net/x"}})
    assert res.status_code == 200 and res.json()["ok"] is True
    assert backend.opened == ["https://newsite.example.net/x"]
    assert "newsite.example.net" not in load_allowed_domains()


def test_api_domain_persist_appends_allowlist(api, allowlist):
    client, _backend = api
    res = client.post("/api/browser/confirm", json={
        "kind": "domain", "action": "fetch_page",
        "params": {"url": "https://newsite.example.net/x"},
        "persist": True})
    assert res.status_code == 200
    assert "newsite.example.net" in load_allowed_domains()


def test_api_persist_domain_derives_from_url_only(api, allowlist):
    """クライアントが params に別ドメインを紛れ込ませても、恒久追記は
    url のホストからのみ導出される。"""
    client, _backend = api
    before = load_allowed_domains()
    res = client.post("/api/browser/confirm", json={
        "kind": "domain", "action": "fetch_page",
        "params": {"url": "https://newsite.example.net/x",
                   "domain": "evil.example.org"},
        "persist": True})
    assert res.status_code == 200
    after = load_allowed_domains()
    assert "evil.example.org" not in after
    assert "newsite.example.net" in after
    assert set(after) - set(before) == {"newsite.example.net"}


def test_api_rejects_unknown_kind_and_action(api, allowlist):
    client, backend = api
    res1 = client.post("/api/browser/confirm", json={
        "kind": "bogus", "action": "click", "params": {}})
    res2 = client.post("/api/browser/confirm", json={
        "kind": "write", "action": "no_such_action", "params": {}})
    assert res1.status_code == 400
    assert res2.status_code == 400
    assert backend.opened == [] and backend.actions == []


# ----------------------------------------------------------------------
# CODE画面（Nacht Code）経路への配線
#
# CODE画面は nachtcode 専用レジストリ（runner._build_registry）を使う。
# ここに browser が登録されていないと、計画に browser ステップを入れられず
# PlanRejected になっていた（承認パネルへ到達できない構造的断絶）。
# 配線後は browser ステップが計画に入り、かつ planner/executor 側の安全機構
# （承認フラグ除去・承認ゲート・隔離層3）が CODE 経路でも効くことを担保する。
# ----------------------------------------------------------------------

class _FakeClient:
    """plan_coding_task に渡す最小のフェイク LLM（実サーバー不使用）。"""

    def __init__(self, plan_obj: dict) -> None:
        self._content = json.dumps(plan_obj)

    def chat(self, model, messages, temperature=0.6, max_tokens=None):
        from app.llm.client import ChatResult
        return ChatResult(model_name="fake", content=self._content, stubbed=False)


def test_code_registry_includes_browser(allowlist):
    """CODE画面のレジストリに browser が配線されている。"""
    from app.llm.client import LLMClient
    from app.tools.nachtcode.runner import _build_registry
    registry = _build_registry(LLMClient())
    assert "browser" in registry.names()
    assert registry.get("browser").supported_actions  # 実体が引ける


def test_code_catalog_lists_browser_actions(allowlist):
    """CODE プランナーが LLM に見せる action カタログに browser.* が載る。"""
    from app.llm.client import LLMClient
    from app.tools.nachtcode.runner import _build_registry, _catalog
    catalog = _catalog(_build_registry(LLMClient()))
    assert "- browser.fetch_page:" in catalog
    assert "- browser.click:" in catalog
    assert "- browser.submit_form:" in catalog


def test_code_plan_accepts_browser_step(allowlist, tmp_path):
    """CODE経路の plan_coding_task が browser ステップを拒否せず計画に入れる。"""
    from app.tools.nachtcode.runner import _build_registry, plan_coding_task
    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
    client = _FakeClient({"steps": [
        {"tool": "browser", "action": "fetch_page",
         "params": {"url": "https://example.com/x"}}]})
    plan = plan_coding_task(
        client, _build_registry(client), str(tmp_path), "example.com を読んで")
    assert plan.source == "llm"
    assert [(s.tool, s.action) for s in plan.steps] == [("browser", "fetch_page")]
    assert plan.steps[0].params == {"url": "https://example.com/x"}


def test_code_plan_strips_human_only_keys_on_browser_step(allowlist, tmp_path):
    """CODE経路でも browser ステップの承認フラグ（LLM由来）が除去される。"""
    from app.tools.nachtcode.runner import _build_registry, plan_coding_task
    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
    client = _FakeClient({"steps": [
        {"tool": "browser", "action": "click",
         "params": {"url": "https://example.com/p", "selector": "#btn",
                    "confirmed": True, "confirm": True,
                    "confirm_token": "deadbeef", "domain_approved": True,
                    "persist_domain": True}}]})
    plan = plan_coding_task(
        client, _build_registry(client), str(tmp_path), "ボタンを押して")
    for key in HUMAN_ONLY_PARAM_KEYS:
        assert key not in plan.steps[0].params, f"{key} が除去されていない"
    assert plan.steps[0].params == {"url": "https://example.com/p",
                                    "selector": "#btn"}


def test_code_path_browser_write_stops_at_preview(allowlist, monkeypatch):
    """CODE経路の execute_plan で、承認なし browser write がプレビューで止まる。"""
    from app.tools.browser import adapter as adapter_module
    from app.tools.nachtcode.runner import _build_registry
    backend = FakeBackend()
    monkeypatch.setattr(adapter_module, "_default_backend", lambda: backend)
    registry = _build_registry(_FakeClient({"steps": []}))
    plan = Plan(steps=(PlanStep(
        tool="browser", action="click",
        params={"url": "https://example.com/p", "selector": "#btn"}),),
        source="llm")
    results = execute_plan(plan, registry, "テスト")
    assert results[0].data.get("needs_confirmation") is True
    assert results[0].data["kind"] == "write"
    assert backend.actions == []  # ページ操作は行われていない


def test_code_path_browser_isolation_layer3_holds(allowlist, monkeypatch):
    """CODE経路でも browser 出力を別 browser ステップへ差し込めない（隔離層3）。"""
    from app.tools.browser import adapter as adapter_module
    from app.tools.nachtcode.runner import _build_registry
    backend = FakeBackend()
    monkeypatch.setattr(adapter_module, "_default_backend", lambda: backend)
    registry = _build_registry(_FakeClient({"steps": []}))
    plan = Plan(steps=(
        PlanStep(tool="browser", action="fetch_page",
                 params={"url": "https://example.com/a"}),
        PlanStep(tool="browser", action="click",
                 params={"url": "https://example.com/b",
                         "selector": "{{step1.output}}"}),
    ), source="llm")
    results = execute_plan(plan, registry, "テスト")
    assert results[0].ok is True
    assert results[1].skipped is True
    assert "インジェクション隔離" in results[1].skip_reason
    assert backend.opened == ["https://example.com/a"]
