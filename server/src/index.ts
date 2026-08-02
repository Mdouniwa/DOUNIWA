/**
 * しゃべる絵本メーカー v5: Mac mini 対話・生成サーバー。
 *
 * PWA(Vercel配信)からTailscale経由でアクセスされる。
 *   POST /api/talk/next  … 対話1ターン(質問生成・音声理解・TTS)
 *   POST /api/book       … 絵本生成ジョブ開始
 *   GET  /api/book/:id   … ジョブ状況ポーリング
 *   GET  /healthz        … 死活監視
 */
import express from 'express';
import cors from 'cors';
import { config } from './env.js';
import { talkRouter } from './routes/talk.js';
import { bookRouter } from './routes/book.js';

const app = express();

app.use(
  cors(
    config.corsOrigins
      ? { origin: config.corsOrigins }
      : {}, // 未設定なら全許可(Tailscaleの閉域網内で使う前提)
  ),
);
// 録音音声(base64)を受けるため上限を広めに取る
app.use(express.json({ limit: '30mb' }));

app.get('/healthz', (_req, res) => {
  res.json({ ok: true, models: {
    chat: config.chatModel,
    story: config.storyModel,
    image: config.imageModel,
    tts: config.ttsModel,
  } });
});

app.use('/api/talk', talkRouter);
app.use('/api/book', bookRouter);

// 予期しないエラーは一律500(子ども向けの文言はクライアント側で出す)
app.use((err: unknown, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
  const message = err instanceof Error ? err.message : 'unknown error';
  console.error('[server]', message);
  res.status(500).json({ error: message });
});

const server = app.listen(config.port, () => {
  console.log(`ehon talk server listening on http://0.0.0.0:${config.port}`);
  console.log(
    `models: chat=${config.chatModel} story=${config.storyModel} image=${config.imageModel} tts=${config.ttsModel}`,
  );
});

// ポート使用中などのlisten失敗は明示的にエラー終了する(exit 0での沈黙死を防ぐ)
server.on('error', (err) => {
  console.error('[server] listen error:', err.message);
  process.exit(1);
});

// launchdのunload(SIGTERM)やCtrl-C(SIGINT)では接続を閉じてから終了する
for (const sig of ['SIGINT', 'SIGTERM'] as const) {
  process.once(sig, () => {
    console.log(`[server] ${sig} received, shutting down`);
    server.close(() => process.exit(0));
    // 進行中の接続が残っていても数秒で確実に終了する
    setTimeout(() => process.exit(0), 3000).unref();
  });
}

// Node 26ではESMのトップレベル評価が完了すると、サーバハンドルが残っていても
// イベントループが空と判定されてプロセスが正常終了してしまうことがある
// (起動ログ直後にexit 0で死ぬ)。トップレベルawaitでモジュール評価を
// サーバのcloseまで保留し、プロセスの寿命をサーバの寿命に明示的に一致させる。
await new Promise<void>((resolve) => server.once('close', resolve));
