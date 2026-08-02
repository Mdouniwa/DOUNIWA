/**
 * Gemini API クライアント(シングルトン)。
 * 認証は GEMINI_API_KEY(APIキー方式)。
 * 旧Vertex AI方式は Gemini Enterprise Agent Platform への改名に伴い廃止した。
 * 課金有効なプロジェクトのAPIキーであれば、入力データが学習に使われない条件は
 * 従来どおり満たせる(子どもの声を扱う上での必須条件)。
 */
import { GoogleGenAI } from '@google/genai';
import { config } from './env.js';

let client: GoogleGenAI | null = null;

export function getAI(): GoogleGenAI {
  if (!client) {
    client = new GoogleGenAI({ apiKey: config.geminiApiKey() });
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
