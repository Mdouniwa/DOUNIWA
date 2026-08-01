import { Router } from 'express';
import { talkNext } from '../talk.js';
import type { TalkNextRequest, TalkTurn } from '../contract.js';

export const talkRouter = Router();

/** リクエスト検証(閉域網前提だが、不正入力でモデル呼び出しを浪費しないため) */
function parseTalkRequest(body: unknown): TalkNextRequest | null {
  if (typeof body !== 'object' || body === null) return null;
  const b = body as Record<string, unknown>;

  const history = b.history;
  if (!Array.isArray(history) || history.length > 20) return null;
  for (const t of history) {
    const turn = t as TalkTurn;
    if (
      typeof turn?.question !== 'string' ||
      typeof turn?.answer !== 'string' ||
      turn.question.length > 500 ||
      turn.answer.length > 500
    ) {
      return null;
    }
  }

  let answer: TalkNextRequest['answer'];
  if (b.answer !== undefined) {
    const a = b.answer as Record<string, unknown>;
    if (typeof a !== 'object' || a === null) return null;
    if (typeof a.text === 'string') {
      if (a.text.length > 500) return null;
      answer = { text: a.text };
    } else if (typeof a.audioBase64 === 'string') {
      // 押しっぱなし録音は長くても数十秒 → base64で20MBを上限とする
      if (a.audioBase64.length > 20 * 1024 * 1024) return null;
      answer = {
        audioBase64: a.audioBase64,
        audioMime: typeof a.audioMime === 'string' ? a.audioMime : undefined,
      };
    } else {
      return null;
    }
  }

  const failCount =
    typeof b.failCount === 'number' && b.failCount >= 0 ? Math.min(b.failCount, 10) : 0;

  return { history: history as TalkTurn[], answer, failCount };
}

talkRouter.post('/next', async (req, res) => {
  const parsed = parseTalkRequest(req.body);
  if (!parsed) {
    res.status(400).json({ error: 'invalid request body' });
    return;
  }
  try {
    const result = await talkNext(parsed);
    res.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'unknown error';
    console.error('[talk]', message);
    res.status(502).json({ error: `talk failed: ${message}` });
  }
});
