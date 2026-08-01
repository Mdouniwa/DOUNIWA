# しゃべる絵本メーカー v5 — Mac mini 対話サーバー

PWA(Vercel配信)から Tailscale 経由で呼ばれる、対話・絵本生成のバックエンド。
Node.js + Express + Vertex AI(`@google/genai`)。フレームワークはこれ以上入れない。

```
[iPad/iPhone PWA] ──Tailscale──→ [このサーバー :8788] ──→ [Vertex AI]
```

## 使用ポート

**8788**(`PORT` 環境変数で変更可)。同居サービスとの衝突確認:

| サービス | ポート |
|---|---|
| n8n | 5678 |
| Dify | 80 / 443 / 3000 / 5001 ほか |
| このサーバー | **8788** |

空きの確認: `lsof -i :8788` が何も返さなければOK。

## セットアップ

### 1. Vertex AI の認証(初回のみ)

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成(既存でも可)
2. 「Vertex AI API」を有効化(APIとサービス → ライブラリ → Vertex AI API → 有効にする)
3. サービスアカウントを作成(IAMと管理 → サービスアカウント → 作成)
   - ロール: **Vertex AI ユーザー**(`roles/aiplatform.user`)
4. 鍵を作成(サービスアカウント → キー → 鍵を追加 → JSON)してダウンロード
5. 鍵ファイルをリポジトリ**外**に置く(例: `~/secrets/ehon-server-sa.json`)
   - **鍵ファイルは絶対にリポジトリにコミットしない**(`.gitignore` 済みだが置かないのが原則)

### 2. サーバー設定

```bash
cd server
npm install
cp .env.example .env
# .env を編集: GOOGLE_CLOUD_PROJECT と GOOGLE_APPLICATION_CREDENTIALS を設定
```

### 3. 起動

```bash
npm run dev      # 開発(ファイル変更で自動再起動)
# または
npm run build && npm start   # 本番
```

動作確認: `curl http://localhost:8788/healthz` → `{"ok":true,...}` が返ればOK。

### 4. launchd で常駐化(Mac mini 運用)

```bash
npm run build
# launchd/com.douniwa.ehon-server.plist の3箇所を自分の環境に書き換える:
#   - node のパス(`which node` の結果)
#   - WorkingDirectory(このリポジトリの server/ の絶対パス)
cp launchd/com.douniwa.ehon-server.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.douniwa.ehon-server.plist
# 確認
launchctl list | grep douniwa
curl http://localhost:8788/healthz
```

ログ: `/tmp/ehon-server.log` / `/tmp/ehon-server.err.log`

### 5. PWAからの接続

iPad側は Tailscale のマシン名で到達する(例: `http://mac-mini.tailnet-xxxx.ts.net:8788`)。
接続先URLはPWAの**親モード → せってい**で設定する(localStorageに保存)。

## API

| メソッド | パス | 役割 |
|---|---|---|
| GET | `/healthz` | 死活監視(使用中モデルも返す) |
| POST | `/api/talk/next` | 対話1ターン: 履歴+答え(テキスト/音声base64) → 相槌+次の質問+選択肢+TTS音声 |
| POST | `/api/book` | 絵本生成ジョブ開始 → `{jobId}` |
| GET | `/api/book/:jobId` | ジョブ状況(`story`→`character`→`pages`→`audio`→`done`)と結果 |

入出力契約は `src/contract.ts`(クライアント側 `src/lib/talkApi.ts` と一致させること)。

## 使用モデル(すべて `.env` で差し替え可)

| 用途 | 既定モデル | 選定理由 |
|---|---|---|
| 対話・質問生成 | `gemini-3.5-flash-lite` | 低レイテンシ。子どもを待たせない |
| 音声理解 | 同上(音声を直接入力) | 文字起こしを挟まず意図を解釈 |
| 物語生成 | `gemini-3.6-flash` | 起承転結の構成力 |
| 挿絵生成 | `gemini-3.1-flash-image` (Nano Banana 2) | 参照画像方式でキャラ一貫性を保持 |
| 音声合成 | `gemini-3.1-flash-tts-preview` | 感情指示可・日本語高品質 |

APIキー方式(AI Studio)ではなく Vertex AI を使う理由: **入力データが学習に使われないのがデフォルト**であり、子どもの声を扱うため。
