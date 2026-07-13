# 動作確認用サンプルタスク

すべて stub モード（.env 未設定）でも通る。実接続後は同じコマンドで実処理になる。

## 基本の一本線確認

```bash
# CODE 分類 -> qwen-35b -> github tool
ai-workspace run "このリポジトリのREADMEを読んで改善点を出して"

# WRITE_NOTE 分類 -> gemma-31b -> obsidian tool
ai-workspace run "Obsidianに今日の設計メモを保存して"

# AUTOMATION 分類 -> qwen-35b -> n8n tool
ai-workspace run "n8nの指定Webhookを叩いて結果を記録して" --param webhook_path=daily-report

# BROWSER 分類 -> browser tool（stub固定）
ai-workspace run "ブラウザでニュースサイトを開いて要約して"

# GENERAL 分類 -> デフォルトモデル・ツールなし
ai-workspace run "MLXとllama.cppの違いを簡単に説明して"
```

## ルーティングの確認

```bash
# 明示指定（クラウドフォールバック）
ai-workspace run "設計の矛盾を洗い出して" --model cloud-claude

# 品質優先（70B級）
ai-workspace run "アーキテクチャをレビューして" --quality

# ルーティング判断のログを見る
ai-workspace run "こんにちは" -v

# 登録モデルと接続状態の一覧
ai-workspace models
```

## ツールパラメータの確認

```bash
# GitHub: リポジトリ指定
ai-workspace run "READMEを読んで" --param repo=owner/name

# Obsidian: タイトル指定
ai-workspace run "メモを保存して" --param "title=設計判断 2026-07-13"
```

## 実行ログの確認

```bash
cat data/memory/runs-*.jsonl | python3 -m json.tool --json-lines
```
