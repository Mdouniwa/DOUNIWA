# 将来拡張TODO一覧（roadmap）

優先度順。各項目に「どこを触るか」を明記してある。

## P1: 実接続の完成（土台の次の一歩）

- [ ] **MLXサーバーの常設化と実モデル検証**
  - M5 Max 上で gemma / qwen の served name を確定し `.env` に固定
  - 触る場所: `.env` のみ（コード変更不要のはず。必要なら `app/llm/models.py`）
- [ ] **タスク分類のLLM化**
  - キーワードルールを軽量ローカルLLMによる分類に置き換える
  - 触る場所: `app/orchestrator/classifier.py`（`classify_task` のシグネチャは維持）
- [ ] **GitHub adapter の本実装**
  - issue/PR 読み書き、リポジトリ検索、ローカル clone 操作
  - 触る場所: `app/tools/github/adapter.py`（action を追加し `supported_actions` に列挙）
- [ ] **Obsidian adapter の本実装**
  - 既存ノート検索・追記、デイリーノート対応、Mac mini vault との同期経路確定
  - 触る場所: `app/tools/obsidian/adapter.py`
- [ ] **n8n adapter の本実装**
  - REST API でのワークフロー一覧・実行・結果ポーリング
  - 触る場所: `app/tools/n8n/adapter.py`

## P2: エージェント能力の強化

- [ ] **LLM function calling によるツール選択**
  - 分類器のヒントではなく、LLM自身に tool/action/params を選ばせる
  - 触る場所: `app/orchestrator/core.py`（ツール選択ステップの差し替え）、
    `app/tools/base.py`（ToolAdapter に JSON schema 出力を追加）
- [ ] **マルチターンセッション**
  - セッションIDと会話履歴の保持
  - 触る場所: `app/memory/store.py`（セッション概念の追加）、`app/cli/main.py`（`chat` サブコマンド）
- [ ] **機微情報ポリシーゲート**
  - タスクに機微タグが付いていたらクラウドモデルへのルーティングを拒否
  - 触る場所: `app/llm/router.py`（route() にポリシーチェック追加）
- [ ] **クラウドフォールバックの自動化**
  - ローカルで品質不足と判断した時のみクラウドへ昇格（明示 opt-in 前提）
  - 触る場所: `app/llm/router.py` / `app/orchestrator/core.py`

## P3: browser / computer-use 統合

- [ ] **browser-use backend の実装**
  - `BrowserBackend` を browser-use で実装（Chrome 接続）
  - 触る場所: `app/tools/browser/` に `browser_use_backend.py` を新設、
    `app/tools/registry.py` で `BrowserAdapter(backend=BrowserUseBackend())` に差し替え
- [ ] **computer-use（macOS操作）の検討**
  - 別 backend として同じ `BrowserBackend` 系譜に載せるか、別 ToolAdapter にするか要設計判断
  - 実験は別リポジトリで行い、成果物のみ移植する（vibe coding ルール準拠）

## P4: 運用・品質

- [ ] **memory の SQLite 化と検索コマンド**（`ai-workspace log search "..."`）
  - 触る場所: `app/memory/store.py`（MemoryStore の実装差し替え）、`app/cli/main.py`
- [ ] **実行ログの Obsidian 自動サマリー**（日次で vault に書き出し）
- [ ] **FastAPI 化**（orchestrator は CLI 非依存なので `app/api/` を被せるだけ）
- [ ] **LLM呼び出しのリトライ・タイムアウト調整・ストリーミング**
  - 触る場所: `app/llm/client.py`
- [ ] **pytest の拡充**（現状は E2E 一本線のみ。adapter 単体テストを追加）

## 判断保留中の論点

- 70B級の具体モデル選定（Llama 3.3 70B を仮置き。品質検証後に確定）
- Mac mini との通信方式（現状 HTTP 直叩き想定。Tailscale 等の VPN 経由を検討）
- クラウドプロキシを LiteLLM に統一するか、provider 別 SDK を使うか
