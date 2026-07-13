# セットアップ手順

対象環境: MacBook Pro M5 Max 128GB（ローカルLLM実行機）+ Mac mini（n8n / Obsidian）。
ただし stub モードなら任意の Python 3.11+ 環境で動く。

## 1. アプリ本体のインストール

```bash
cd ai-workspace
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

開発用（テスト含む）:

```bash
pip install -e ".[dev]"
```

## 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env` は gitignore 済み。**APIキー等は必ず .env にのみ書く。**
全項目が空でも stub モードで動作確認できる。

## 3. stub モードでの動作確認（LLMサーバー不要）

```bash
ai-workspace run "このリポジトリのREADMEを読んで改善点を出して"
ai-workspace models
```

`[stub:...]` 付きの応答と `data/memory/runs-YYYY-MM.jsonl` への記録が確認できれば、
一本線は通っている。

## 4. ローカルLLM（MLX）の実接続

### mlx_lm.server を使う場合

```bash
pip install mlx-lm
# 例: Qwen3 32B の 4bit 量子化
mlx_lm.server --model mlx-community/Qwen3-32B-4bit --port 8080
```

### LM Studio を使う場合

1. LM Studio でモデルをロード
2. Developer タブから Local Server を起動（既定ポート 1234）

### .env の設定

```bash
LOCAL_LLM_BASE_URL=http://localhost:8080/v1   # LM Studio なら http://localhost:1234/v1
QWEN_SERVED_NAME=mlx-community/Qwen3-32B-4bit  # サーバーのロード名に合わせる
DEFAULT_MODEL=qwen-35b
```

サーバー側のモデルロード名と `*_SERVED_NAME` が一致していないと 404 になる点に注意。
確認:

```bash
curl http://localhost:8080/v1/models
ai-workspace run "こんにちは。自己紹介して" -v
```

`-v` でルーティング判断のログが出る。応答に `[stub:...]` が付かなければ実接続成功。

## 5. 外部ツールの実接続（任意）

### GitHub

```bash
GITHUB_TOKEN=ghp_xxx            # repo read 権限があれば十分
GITHUB_DEFAULT_REPO=owner/name  # --param repo=owner/name でも上書き可
```

### Obsidian

```bash
OBSIDIAN_VAULT_PATH=/Users/you/Obsidian/MainVault
OBSIDIAN_NOTE_FOLDER=ai-workspace
```

vault パスが存在すれば、`ai-workspace run "Obsidianにメモを保存して"` で
実ファイルが書かれる。Mac mini 側 vault を使う場合は同期フォルダのパスを指定。

### n8n（Mac mini）

```bash
N8N_WEBHOOK_BASE_URL=http://mac-mini.local:5678/webhook
```

```bash
ai-workspace run "n8nのWebhookを叩いて" --param webhook_path=my-hook
```

## 6. クラウドLLMフォールバック（任意）

OpenAI互換プロキシ（LiteLLM 等）を立てて URL を設定するのが推奨構成。

```bash
ANTHROPIC_BASE_URL=http://localhost:4000/v1
ANTHROPIC_API_KEY=sk-xxx
```

使用は明示指定時のみ:

```bash
ai-workspace run "..." --model cloud-claude
```

## トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| 応答が常に `[stub:...]` | `LOCAL_LLM_BASE_URL` 未設定、またはサーバー未起動。`curl $LOCAL_LLM_BASE_URL/models` で確認 |
| 404 / model not found | `*_SERVED_NAME` とサーバーのロード名の不一致 |
| `unknown model 'xxx'` | `ai-workspace models` で登録名を確認 |
| Obsidian が stub のまま | `OBSIDIAN_VAULT_PATH` のディレクトリが存在しない |
