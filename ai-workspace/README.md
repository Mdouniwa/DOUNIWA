# ai-workspace

ローカルLLM（MLX系）を中心に、ターミナル開発支援・外部ツール連携・
将来の browser / computer-use 統合を見据えた **個人用AIワークスペースのPoC土台**。

完成品ではなく「後で確実に育てられる構造」を優先している。
現段階では実LLM・実ツール未接続でも、stub で end-to-end の一本線が動く。

## できること（現時点）

```
自然言語入力 -> タスク分類 -> モデル選択 -> ツール呼び出し(stub可) -> LLM整形 -> 実行ログ保存
```

- `ai-workspace run "..."` で自然言語タスクを実行
- model名（`gemma-31b` / `qwen-35b` / `llama-70b` / `cloud-claude` / `cloud-gemini`）による内部ルーティング
- GitHub / Obsidian / n8n の最小接続口（環境変数を設定すれば実接続、なければ stub）
- browser / computer-use の抽象インターフェース（実装は今後）
- 実行ログの JSONL 保存（`data/memory/`）

## クイックスタート

```bash
cd ai-workspace
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # 必要な値を埋める（全部空でも stub で動く）

# 動作確認（LLMサーバー不要・stubで通る）
ai-workspace run "このリポジトリのREADMEを読んで改善点を出して"
ai-workspace run "Obsidianに今日の設計メモを保存して"
ai-workspace run "n8nの指定Webhookを叩いて結果を記録して" --param webhook_path=my-hook
ai-workspace models   # 登録済みモデル一覧
```

ローカルLLMを実接続する場合は M5 Max 上で MLX 系 OpenAI互換サーバーを起動し、
`.env` の `LOCAL_LLM_BASE_URL` を設定する。詳細は [docs/setup.md](docs/setup.md)。

## モデル方針

| model名 | tier | 用途 |
|---|---|---|
| `qwen-35b` | workhorse | デフォルト。コード/ツール呼び出し系 |
| `gemma-31b` | workhorse | 日本語/要約/メモ系 |
| `llama-70b` | quality | `--quality` 指定時のみ。速度より品質 |
| `cloud-claude` / `cloud-gemini` | cloud | 明示指定時のみのフォールバック。機微情報は渡さない |

## ディレクトリ構成

```
app/
  llm/           モデル設定・ルーティング・OpenAI互換呼び出し
  orchestrator/  タスク受理・分類・モデル選択・ツール呼び出し制御
  tools/         github / obsidian / n8n / browser + 共通インターフェース
  memory/        実行ログ・保存ルール
  cli/           CLIエントリーポイント
docs/
  architecture.md  設計の全体像と拡張ポイント
  setup.md         セットアップ手順（MLXサーバー起動含む）
  roadmap.md       将来拡張TODO一覧
examples/
  sample_tasks.md  動作確認用サンプルタスク集
```

## 次の実装者へ

まず [docs/architecture.md](docs/architecture.md) を読むこと。
「どこに何を足すか」は各モジュールの docstring と [docs/roadmap.md](docs/roadmap.md) に書いてある。
棄却済みのアプローチは [REJECT_LOG.md](REJECT_LOG.md) を参照。
