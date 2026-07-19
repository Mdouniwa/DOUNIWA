# アーキテクチャ説明書

## 全体像

```
┌──────────────┐
│  app/cli     │  ユーザー入口（argparse）
└──────┬───────┘
       │ task_text, --model, --quality, --param
┌──────▼───────────────────────────────────────┐
│  app/orchestrator                            │
│   classifier.py  タスク分類（ルールベース）   │
│   core.py        制御フローのみを持つ         │
└──┬───────────┬───────────────┬───────────────┘
   │           │               │
┌──▼─────┐ ┌──▼──────────┐ ┌──▼──────────┐
│app/llm │ │ app/tools   │ │ app/memory  │
│models  │ │ base.py     │ │ store.py    │
│router  │ │ registry.py │ │ (JSONL追記) │
│client  │ │ github/     │ └─────────────┘
└────────┘ │ obsidian/   │
           │ n8n/        │
           │ browser/    │
           └─────────────┘
```

end-to-end の一本線:

```
自然言語入力 -> classify_task() -> ModelRouter.route()
  -> ToolAdapter.execute()（必要時のみ・stub可）
  -> LLMClient.chat()（未接続なら stub 応答）
  -> MemoryStore.save()
```

## 責務分離の原則

| 層 | 知っていること | 知らないこと |
|---|---|---|
| cli | 引数の解釈と出力整形 | 分類・ルーティング・ツールの中身 |
| orchestrator | 制御フロー（順序） | モデルのURL、ツールの実装詳細 |
| llm | model名 -> endpoint/provider/tier の解決と呼び出し | タスクの意味、ツール |
| tools | 各外部サービスとの接続 | どのモデルが使われるか |
| memory | 記録形式と保存先ルール | タスクの実行方法 |

orchestrator は `ToolAdapter` / `ModelRouter` / `MemoryStore` という
インターフェースにのみ依存する。実装の差し替えはコンストラクタ注入で行える
（テスト・実験でモックに差し替え可能）。

## モデルルーティング

### 設計

- **model名は内部名**（`qwen-35b` 等）。サーバー側の実モデル名
  （`served_model_name`）とは分離してあり、サーバーのロード名が変わっても
  内部名は安定する。
- `ModelSpec` は endpoint/APIキーを **環境変数名として** 持ち、値は実行時に解決。
  コードに機密情報が入らない。
- ルーティング優先順位:
  1. `--model` による明示指定
  2. `--quality` フラグ（70B級 = QUALITY tier）
  3. タスク種別ごとのポリシー（`router.py` の `_POLICY` 辞書）
  4. `DEFAULT_MODEL`（既定 `qwen-35b`）

### tier の思想

- `workhorse`（31B〜35B級）: 常用。速度と品質のバランス。
- `quality`（70B級）: 自動では選ばれない。明示要求時のみ。
- `cloud`: 明示指定時のみ。選択時は警告ログを出す（機微情報ガードの布石）。

### モデルの追加方法

`app/llm/models.py` に `ModelSpec` を1つ `_register()` するだけ。
エンドポイントを分けたい場合は `endpoint_env` に別の環境変数名を指定する。

## ツールアダプタ

### インターフェース

```python
class ToolAdapter(ABC):
    name: str
    supported_actions: tuple[str, ...]
    def execute(self, request: ToolRequest) -> ToolResult: ...
```

- 失敗は例外ではなく `ToolResult(ok=False)` で返す（orchestrator を落とさない）。
- 未設定・未接続の場合は `ToolResult(stubbed=True)` の stub 応答で処理を継続する。
  **「設定がなくても一本線が通る」ことが PoC の生命線**なので、この規約は維持すること。

### ツールの追加方法

1. `app/tools/<name>/adapter.py` に `ToolAdapter` 実装を作る
2. `app/tools/registry.py` の `build_default_registry()` に登録（1行）
3. `app/orchestrator/classifier.py` の `_RULES` にキーワード -> ツール対応を追加

### browser の抽象層

`app/tools/browser/adapter.py` は二段構え:

- `BrowserAdapter`: orchestrator から見える通常の ToolAdapter
- `BrowserBackend`(ABC): `open_url` / `act` / `extract` を持つ差し込み口

将来 browser-use / Playwright / computer-use を導入する時は
`BrowserBackend` を実装して `BrowserAdapter(backend=...)` を registry に
渡すだけでよい。orchestrator・classifier は変更不要。

## タスク分類

PoC段階はキーワードルール（`classifier.py` の `_RULES`）。
将来は軽量ローカルLLMによる分類に差し替えるが、
`classify_task(str) -> Classification` のシグネチャは維持する。
呼び出し側は分類の実装方式を知らない。

## memory層

- JSONL 追記のみ（`data/memory/runs-YYYY-MM.jsonl`、月次ローテーション）
- 1タスク = 1レコード（分類結果・ルーティング理由・ツール出力・LLM出力・stub有無）
- `data/` は gitignore。機微情報はローカルから出さない
- 追記のみで書き換えない（後から監査できる）

## プライバシー方針

- デフォルトはすべてローカルモデル。クラウドは明示指定時のみ
- クラウドモデル選択時は警告ログを出す
- 将来: ルーター段階で「機微情報タグ付きタスクはクラウド不可」の
  ポリシーゲートを入れる（roadmap 参照）

## 意図的にやっていないこと

- FastAPI / HTTPサーバー化（CLIで十分な段階。orchestrator は CLI 非依存なので後で被せられる）
- LLM function calling によるツール選択(まずルールで一本線を通し、次段でLLM分類に差し替える)
- ストリーミング応答・マルチターン会話（セッション概念は memory 層拡張で入れる）
- リトライ・レート制御（実運用で必要になってから client.py に足す）
