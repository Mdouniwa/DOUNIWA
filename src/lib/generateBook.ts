/**
 * クライアント側の絵本生成: Mac mini対話サーバーのジョブAPIを呼び出し、
 * 返ってきたbase64画像・音声をBlobに変換して下書きページ(DraftPage)を組み立てる。
 * 画像は既存の resizeImage で本画像+サムネイルに整える。
 */
import {
  startBookJob,
  getBookJob,
  base64ToBlob,
  type BookJobResponse,
  type BookJobStatus,
  type TalkTurn,
} from './talkApi';
import { resizeImage } from './imageResize';
import type { DraftPage } from '../screens/create/draft';

export interface GeneratedBook {
  title: string;
  pages: DraftPage[];
}

/** 対話からの生成結果: 主人公の基準画像も持つ(参照画像方式) */
export interface TalkGeneratedBook extends GeneratedBook {
  characterRef: { imageBlob: Blob; thumbBlob: Blob };
}

/** ジョブのポーリング間隔と上限(挿絵6枚+音声で30秒〜2分程度を想定) */
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * 対話ログから絵本を生成する(Mac mini対話サーバーのジョブAPIを使用)。
 * 進捗はonProgressで通知される(生成中画面の演出用)。
 */
export async function generateBookFromTalk(
  conversation: TalkTurn[],
  onProgress?: (status: BookJobStatus, progress: number) => void,
): Promise<TalkGeneratedBook> {
  const { jobId } = await startBookJob(conversation);

  const deadline = Date.now() + POLL_TIMEOUT_MS;
  let job: BookJobResponse;
  for (;;) {
    await sleep(POLL_INTERVAL_MS);
    job = await getBookJob(jobId);
    onProgress?.(job.status, job.progress);
    if (job.status === 'done') break;
    if (job.status === 'error') throw new Error(job.error ?? 'generation failed');
    if (Date.now() > deadline) throw new Error('generation timed out');
  }

  const result = job.result;
  if (!result) throw new Error('job finished without result');

  const pages: DraftPage[] = [];
  for (const p of result.pages) {
    const rawImage = base64ToBlob(p.imageBase64, p.imageMime || 'image/png');
    const { imageBlob, thumbBlob } = await resizeImage(rawImage);
    const audioBlob = p.audioBase64
      ? base64ToBlob(p.audioBase64, p.audioMime || 'audio/wav')
      : null;
    pages.push({
      id: crypto.randomUUID(),
      imageBlob,
      thumbBlob,
      captionText: p.text,
      audioBlob,
      audioMime: audioBlob ? p.audioMime || 'audio/wav' : null,
      soundEffect: null,
      narrationSource: 'generated',
    });
  }

  // 主人公の基準画像も保存用に整える(親モードや再生成で使えるように)
  const characterRef = await resizeImage(
    base64ToBlob(result.characterRefBase64, result.characterRefMime || 'image/png'),
  );

  return { title: result.title, pages, characterRef };
}
