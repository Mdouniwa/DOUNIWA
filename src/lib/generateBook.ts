/**
 * クライアント側の絵本生成: `/api/generate-book` を呼び出し、
 * 返ってきたbase64画像・音声をBlobに変換して下書きページ(DraftPage)を組み立てる。
 * 画像は既存の resizeImage で本画像+サムネイルに整える。
 */
import type { GenerateBookRequest, GenerateBookResponse, GenerateBookError } from './generateApi';
import {
  startBookJob,
  getBookJob,
  type BookJobResponse,
  type BookJobStatus,
  type TalkTurn,
} from './talkApi';
import { resizeImage } from './imageResize';
import type { DraftPage } from '../screens/create/draft';

function base64ToBlob(base64: string, mime: string): Blob {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

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

/** アイコンキーワードから絵本を生成し、DraftPage配列に変換して返す */
export async function generateBook(iconKeywords: string[]): Promise<GeneratedBook> {
  const res = await fetch('/api/generate-book', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ icons: iconKeywords } satisfies GenerateBookRequest),
  });

  if (!res.ok) {
    let message = `generation failed (${res.status})`;
    try {
      const body = (await res.json()) as GenerateBookError;
      if (body.error) message = body.error;
    } catch {
      // JSON以外のエラー応答は無視
    }
    throw new Error(message);
  }

  const data = (await res.json()) as GenerateBookResponse;

  const pages: DraftPage[] = [];
  for (const p of data.pages) {
    const rawImage = base64ToBlob(p.imageBase64, p.imageMime || 'image/png');
    // 生成画像を本画像(長辺1500px)+サムネ(300px)に整える(既存ロジック再利用)
    const { imageBlob, thumbBlob } = await resizeImage(rawImage);
    const audioBlob =
      p.audioBase64 ? base64ToBlob(p.audioBase64, p.audioMime || 'audio/wav') : null;
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

  return { title: data.title, pages };
}
