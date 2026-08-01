import { Router } from 'express';

/** 対話ルーター(Phase 2 で実装)。 */
export const talkRouter = Router();

talkRouter.post('/next', (_req, res) => {
  res.status(501).json({ error: 'not implemented yet (Phase 2)' });
});
