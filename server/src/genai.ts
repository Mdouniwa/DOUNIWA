/**
 * Vertex AI クライアント(シングルトン)。
 * AI Studio の APIキー方式ではなく Vertex AI を使う。
 * 理由: 入力データが学習に使われないのがデフォルトで、子どもの声を扱う上で適切。
 * 認証はサービスアカウント鍵(GOOGLE_APPLICATION_CREDENTIALS のパス指定)で行われる。
 */
import { GoogleGenAI } from '@google/genai';
import { config } from './env.js';

let client: GoogleGenAI | null = null;

export function getAI(): GoogleGenAI {
  if (!client) {
    client = new GoogleGenAI({
      vertexai: true,
      project: config.googleCloudProject(),
      location: config.googleCloudLocation,
    });
  }
  return client;
}

/** レスポンスのpartsから最初のinlineData(base64バイナリ)を取り出す */
export function firstInlineData(resp: {
  candidates?: Array<{
    content?: { parts?: Array<{ inlineData?: { data?: string; mimeType?: string } }> };
  }>;
}): { data: string; mimeType: string } | null {
  const parts = resp.candidates?.[0]?.content?.parts ?? [];
  for (const p of parts) {
    if (p.inlineData?.data) {
      return { data: p.inlineData.data, mimeType: p.inlineData.mimeType ?? '' };
    }
  }
  return null;
}
