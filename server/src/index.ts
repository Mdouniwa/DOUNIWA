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

app.listen(config.port, () => {
  console.log(`ehon talk server listening on http://0.0.0.0:${config.port}`);
  console.log(
    `models: chat=${config.chatModel} story=${config.storyModel} image=${config.imageModel} tts=${config.ttsModel}`,
  );
});
