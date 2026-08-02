# しゃべるえほん(しゃべる絵本メーカー v6)

家族専用の「しゃべる絵本メーカー」PWA。**「えほんの精」が子どもに話しかけ、子どもが声かタップで答えると、その会話から絵本(物語・挿絵・ナレーション音声)ができあがります。** iPad(Safari・ホーム画面追加)で読む家庭内PoCです。

- **つくる(2歳も5歳も同じフロー)**: えほんの精の質問に「声(押しっぱなしマイク)」か「アイコンタップ」で5問くらい答える → AIが絵本を生成 → 気に入らなければ自分の声で録り直し
- **よむ**: 大きな左右ボタンでページ送り、画像タップで効果音、本をめくるアニメーション
- **親**: ホーム右上隅を**3秒長押し**で親モード(削除・並び替え・表紙変更・よみあげ文編集・対話サーバーURL設定)

## アーキテクチャ

```
[iPad/iPhone PWA]
    │
    ├─ 静的配信・絵本閲覧 ────→ [Vercel](静的サイトのみ。サーバーレス関数なし)
    │
    └─ 対話・生成 ──Tailscale──→ [Mac mini 対話サーバー :8788]
                                        │
                                        └──→ [Gemini API](Gemini / Nano Banana 2 / Gemini TTS)
```

- **対話と生成のときだけ**ネットワーク(Tailscale経由でMac mini)が必要です。生成済み絵本の閲覧・再生は**完全オフライン**(画像・音声はBlobとしてIndexedDBに保存)。
- バックエンドは **`server/`(Node.js + Express + `@google/genai`)** に集約。v4のVercelサーバーレス関数は廃止しました。
- **認証は課金有効プロジェクトのGemini APIキー方式**(`GEMINI_API_KEY`)。課金有効キーなら**入力データが学習に使われない**条件を満たせるため、子どもの声をそのまま音声理解に渡せる。旧Vertex AI(サービスアカウント鍵)方式は、Gemini Enterprise Agent Platform への改名に伴い廃止。

## セットアップ(Mac mini)

詳細は [server/README.md](server/README.md)。要点:

### 1. Gemini APIキーの用意(初回のみ)

1. **課金が有効な** Google Cloud プロジェクトで Gemini API の APIキーを発行
2. キーは `server/.env` にのみ書く。**絶対にコミットしない**(無課金の無料枠キーは入力が学習に使われる可能性があるため使わない)

### 2. サーバー起動

```bash
cd server
npm install
cp .env.example .env   # GEMINI_API_KEY を記入
npm run dev            # 開発
npm run build && npm start   # 本番
curl http://localhost:8788/healthz   # 動作確認
```

**ポートは 8788**(n8n=5678、Dify=80/3000/5001系と衝突しません。変更は `.env` の `PORT`)。

### 3. launchd常駐化

`server/launchd/com.douniwa.ehon-server.plist` のパスを書き換えて `~/Library/LaunchAgents/` にコピーし `launchctl load`。手順の全文は [server/README.md](server/README.md)。

### 4. PWA側の接続先設定

iPadでアプリを開き、**親モード(ホーム右上3秒長押し)→ せってい → 対話サーバーURL** に Tailscale のアドレスを入れる(例 `http://mac-mini.tailnet-xxxx.ts.net:8788`)。「せつぞくかくにん」で ✅ が出ればOK。
開発時は `VITE_TALK_SERVER_URL` でビルド時デフォルトも指定可能(未設定なら `http://localhost:8788`)。

## 技術構成

- Vite + React + TypeScript(PWA: `vite-plugin-pwa`)
- IndexedDB(`idb`)— 画像・音声・対話ログ・主人公基準画像を端末内保存
- 対話サーバー: Node.js + Express + `@google/genai`(Gemini APIキー方式)
- 録音: MediaRecorder API(iOSは `audio/mp4`、他は `webm`)。対話の音声回答も同じ仕組み
- 読み上げフォールバック: Web Speech API(サーバーTTSが失敗しても進める)
- 効果音: WebAudio合成(外部音源ファイルなし)

### 使用モデル(すべて `server/.env` で差し替え可能)

| 用途 | 既定モデル | 環境変数 | 選定理由 |
|---|---|---|---|
| 対話・質問生成 | `gemini-3.5-flash-lite` | `CHAT_MODEL` | 低レイテンシ最優先。子どもを待たせない |
| 音声理解 | 同上(音声を直接入力) | — | 文字起こしを挟まず、幼児の発話の意図を直接解釈 |
| 物語生成 | `gemini-3.6-flash` | `STORY_MODEL` | 起承転結の構成力が必要なため上位Flash |
| 挿絵生成 | `gemini-3.1-flash-image`(Nano Banana 2) | `IMAGE_MODEL` | **参照画像方式**でキャラクターの見た目を全ページ固定 |
| 音声合成 | `gemini-3.1-flash-tts-preview` | `TTS_MODEL` | 話し方を自然言語で指示可能・日本語高品質(プレビュー版のため割当制限に注意) |
| TTSの声 | `Sulafat` | `TTS_VOICE` | 若く澄んだやさしいお姉さん声(公式: Warm。候補8声のF0比較で中間域)。話し方は `TTS_STYLE` で調整可 |

> 音声はGeminiが**生のPCM**で返すため、サーバー側でWAVヘッダを付けて `audio/wav` にして返します(iOS Safari対応)。

### 挿絵の一貫性(v4からの最重要改善)

v4は各ページを独立生成していたため主人公の見た目がページごとにブレていました。v5〜v7では:

1. 物語生成時に**登場人物ごと(最大5人)の見た目**を出力させる
2. **全員を1枚に並べたキャラクターシート**を生成(主人公だけだとパパ・ママ等がページごとに別人になるため)
3. 各ページはシートを**参照画像として添付**し、さらに各人物の特徴テキストを併記して二重に固定
4. 全ページ同じキャラクターの絵本になる(シートは絵本と一緒にIndexedDBへ保存)

### アート素材(v6)

UIのアート素材(えほんの精・ロゴ・背景・装飾イラスト・UIパーツ、計24点)は
**ランタイム生成せず**、開発時に生成した画像を静的同梱(API依存・コストゼロ)。
パスは `src/lib/artAssets.ts` に集約。

```bash
# 全素材を生成(生成済みファイルはスキップ)
node --env-file="$HOME/.ehon-art.env" scripts/generate-art.mjs

# 部分再生成(グループ: fairy | logo | bg | deco | ui)
node --env-file="$HOME/.ehon-art.env" scripts/generate-art.mjs --only=fairy --force
```

- 認証は `GEMINI_API_KEY`(AI Studioキー。素材はプロンプトのみで個人情報を含まないためVertex不要)。env ファイルは `GEMINI_API_KEY=...` の1行
- モデルは `IMAGE_MODEL` で差し替え可(既定 `gemini-3.1-flash-image` = Nano Banana 2)
- えほんの精は1枚目(normal)を基準画像に、残り表情を**参照画像方式**で生成して同一キャラクターに揃える
- 透過素材はマゼンタ単色背景で生成→スクリプト内のクロマキー処理で抜く
- sharpでリサイズ+圧縮(1枚200KB以下目安)。一時ディレクトリ経由で書くため途中失敗しても既存素材は壊れない
- コスト目安: 全素材再生成で約$1(24枚 × 約$0.04)
- 旧スクリプト `scripts/generate-fairy.mjs` / `scripts/fairy-placeholder.mjs` はv5時代のもの(fairyのみ)。v6では `generate-art.mjs` を使う

### 1冊あたりの想定コスト概算

6ページ+基準画像1枚、対話5〜7ターンの場合(2026年時点の価格・約¥155/$で試算):

- 対話(flash-lite テキスト+音声理解+質問TTS): **約¥5**
- 物語(gemini-3.6-flash): **¥1未満**
- 挿絵: 7枚 × 約$0.04 ≈ **約¥43**
- ページ音声(TTS 約1分): **約¥5**
- **合計: おおむね ¥50〜70/冊**

## 開発

```bash
npm install
npm run dev     # フロントエンド(対話・生成にはserverの起動が必要)
npm run build   # 型チェック + 本番ビルド(dist/)
npm run lint    # oxlint
cd server && npm run typecheck   # サーバーの型チェック
```

- アプリアイコン変更: `scripts/icon.svg` を編集して `node scripts/generate-icons.mjs`
- アート素材再生成: 上記「アート素材(v6)」参照(`npm run art -- --only=...` でも可)
- 固定セリフ音声の再生成: `node --env-file="$HOME/.ehon-art.env" scripts/generate-voice.mjs`
  (1問目は固定でサーバーを呼ばないため、`public/audio/first-question.m4a` を同梱。声を変えたら再生成すること)

## Vercelへのデプロイ

v5からVercelは**静的配信のみ**(サーバーレス関数・環境変数は不要)。

1. リポジトリをGitHubにpush → Vercelで Import(Framework: Vite / Build: `npm run build` / Output: `dist`)
2. 発行されたURLをiPadで開き、ホーム画面に追加
3. 親モードで対話サーバーURL(Tailscale)を設定

> PWAからMac miniへは、iPad側にもTailscaleを入れて同じテールネットに参加させてください。

## iPadのホーム画面に追加する手順

1. iPadの **Safari** でデプロイしたURLを開く
2. 共有ボタン(□に↑)→ **「ホーム画面に追加」**
3. 以後はホーム画面のアイコンから起動(フルスクリーン)

> 絵本の**対話・生成**はMac miniに繋がることが必要です。生成済み絵本の閲覧は機内モードでも動きます。
> ストレージ永続化(`navigator.storage.persist()`)を起動時に要求します。7日以上開かないとSafariの仕様でデータが消える可能性があるため、ときどき開いてください。

## 実機確認チェックリスト(iPad / iPhone)

自動E2Eテストは行わない方針のため、以下を実機で確認してください。

### 初回セットアップ
- [ ] Mac miniで `curl http://localhost:8788/healthz` が `{"ok":true,...}` を返す
- [ ] iPadのTailscaleがON、親モードの「せつぞくかくにん」で ✅ が出る
- [ ] ホーム画面に追加でき、起動時フルスクリーン
- [ ] 機内モードでも生成済み絵本の閲覧はできる(オフライン動作)

### 対話フロー(2歳・5歳)
- [ ] 「つくる」→ えほんの精が現れ、最初の質問が**音声で**読み上げられる
- [ ] マイクを**押している間だけ**録音され、離すと精が答えを拾って次の質問をする(**初回はマイク許可ダイアログ**)
- [ ] 選択肢アイコンのタップでも同じように進む(声とタップを混ぜてもよい)
- [ ] 質問と無関係な答えでも否定されず、お話に取り込まれる
- [ ] 聞き取れないとき「もういっかい いってくれる?」と音声で聞き返される。3回失敗すると選択肢が大きく2列表示になる
- [ ] マイク許可を拒否してもタップだけで最後まで進める
- [ ] 花の進捗が答えるたびに増え、5つ集まると生成に進む
- [ ] 対話サーバーを止めた状態だと「もういちど」ボタンが出て、再起動後にリトライできる

### 生成〜保存
- [ ] 生成中: 精のアニメーション+答えた内容が順に浮かぶ+進捗バーが動く
- [ ] 1分前後で「できあがり確認」に進み、**全ページで主人公の見た目が一貫している**
- [ ] 「こえを きく」で生成音声、「🎤」で録り直し、効果音チップを選べる
- [ ] 表紙・タイトルを決めて「かんせい!」→ ホームに新しい絵本が出る

### 再生・親モード(v4から不変であることの確認)
- [ ] ページを開くと音声が自動再生され、無いページはWeb Speech TTSで読まれる
- [ ] 画像タップの効果音、◀▶ページ送り、めくりアニメーションが従来どおり
- [ ] 親モードでタイトル・よみあげ文編集、並び替え、表紙変更、2段階削除が動く
- [ ] **v4以前に作った絵本もそのまま開ける**

## やらないこと(スコープ外)

外部共有・アカウント・課金UI・動画編集・クラウド同期・アナリティクス・複雑ジェスチャ・レート制限(家庭内PoC・Tailscale閉域網のため)
