/**
 * クライアント側の絵本生成: `/api/generate-book` を呼び出し、
 * 返ってきたbase64画像・音声をBlobに変換して下書きページ(DraftPage)を組み立てる。
 * 画像は既存の resizeImage で本画像+サムネイルに整える。
 */
import type { GenerateBookRequest, GenerateBookResponse, GenerateBookError } from './generateApi';
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
