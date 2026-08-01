import { Router } from 'express';

/** 絵本生成ルーター(Phase 5 で実装)。 */
export const bookRouter = Router();

bookRouter.post('/', (_req, res) => {
  res.status(501).json({ error: 'not implemented yet (Phase 5)' });
});

bookRouter.get('/:jobId', (_req, res) => {
  res.status(501).json({ error: 'not implemented yet (Phase 5)' });
});
