import { Router } from 'express';
import { startBookJob, getJob } from '../book.js';
import type { TalkTurn } from '../contract.js';

export const bookRouter = Router();

/** 対話ログの検証(不正入力でモデル呼び出しを浪費しない) */
function parseConversation(body: unknown): TalkTurn[] | null {
  if (typeof body !== 'object' || body === null) return null;
  const conversation = (body as { conversation?: unknown }).conversation;
  if (!Array.isArray(conversation) || conversation.length === 0 || conversation.length > 20) {
    return null;
  }
  for (const t of conversation) {
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
  return conversation as TalkTurn[];
}

bookRouter.post('/', (req, res) => {
  const conversation = parseConversation(req.body);
  if (!conversation) {
    res.status(400).json({ error: 'conversation must be a non-empty array of {question, answer}' });
    return;
  }
  const jobId = startBookJob(conversation);
  res.status(202).json({ jobId });
});

bookRouter.get('/:jobId', (req, res) => {
  const job = getJob(req.params.jobId);
  if (!job) {
    res.status(404).json({ error: 'job not found (expired or unknown)' });
    return;
  }
  res.json(job);
});
