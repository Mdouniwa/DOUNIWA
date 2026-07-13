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

### 4-a. M5 Max 常駐 FastAPI プロキシ（11437）を使う場合【推奨・実機】

M5 Max 上で `~/local_mlx_server/` のプロキシが稼働している場合はそれをそのまま使う。
**プロキシ本体（plist / start_servers.sh 含む）には変更・再起動を加えないこと。**

手順（すべて read-only）:

```bash
# 1. LISTEN 確認（11435-11438）
lsof -iTCP -sTCP:LISTEN -n -P | grep -E '1143[5-8]'

# 2. 実際に通る model 名をライブで確認（Obsidianノート等の記録は参考値。ライブを正とする）
curl -s http://localhost:11437/v1/models | python3 -m json.tool

# 3. 生 curl で疎通確認（choices[0].message.content が返ること）
curl -s http://localhost:11437/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<手順2の実名>","messages":[{"role":"user","content":"1+1は？"}]}'
```

プロキシは model 名の**部分一致**でルーティングする（proxy_server.py を読んで確認）:

| 名前の条件 | 実体 | ai-workspace 側の割り当て |
|---|---|---|
| "26b" を含む | Gemma 26B（高速・日本語◎） | `GEMMA_SERVED_NAME`（workhorse・既定） |
| "gemma" かつ "31b" を含む | Gemma 31B（高品質・低速） | `LLAMA70B_SERVED_NAME`（quality 枠） |
| "qwen" を含む | Qwen 35B（Tool Calling向き） | `QWEN_SERVED_NAME` |

.env の設定例（**served name は必ず手順2のライブ出力に置き換える**）:

```bash
LOCAL_LLM_BASE_URL=http://localhost:11437/v1
LOCAL_LLM_API_KEY=dummy          # プロキシがキー不要ならダミーで可
DEFAULT_MODEL=gemma-31b          # 内部名。served は 26B を指すので既定が高速系になる
GEMMA_SERVED_NAME=<26bを含むライブの実名>
QWEN_SERVED_NAME=<qwenを含むライブの実名>
LLAMA70B_SERVED_NAME=<gemmaかつ31bを含むライブの実名>
```

注意:

- 内部名 `llama-70b` は「品質優先枠（--quality）」の抽象名。実体は Gemma 31B を
  割り当ててよい（内部名と served name の分離はこのための設計）。
- Gemma 31B は初回コールに 10〜30 秒のコールドスタートがある。クライアントの
  タイムアウトは既定 120 秒（`app/llm/client.py` の `DEFAULT_TIMEOUT_S`）なので
  そのままで足りる。
- localhost で繋がらない場合のみ Tailscale IP（例: `http://100.105.91.109:11437/v1`）
  に切り替える。IP はコードに書かず .env のみ。

### 4-b. mlx_lm.server を単体で使う場合

```bash
pip install mlx-lm
# 例: Qwen3 32B の 4bit 量子化
mlx_lm.server --model mlx-community/Qwen3-32B-4bit --port 8080
```

### 4-c. LM Studio を使う場合

1. LM Studio でモデルをロード
2. Developer タブから Local Server を起動（既定ポート 1234）

### 4-b / 4-c の .env 設定

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
