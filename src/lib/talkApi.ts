/**
 * Mac mini 対話サーバーとの入出力契約とfetchヘルパー。
 * サーバー側の server/src/contract.ts と必ず一致させること
 * (サーバーは別パッケージのため、既存 generateApi.ts と同じ「契約ファイルを両側に置く」方針)。
 */
import { getTalkServerUrl } from './serverConfig';

/** えほんの精の表情(public/fairy/fairy-{expression}.png と対応) */
export type FairyExpression = 'normal' | 'happy' | 'thinking' | 'surprised' | 'cheer';

/** 対話ログの1往復 */
export interface TalkTurn {
  question: string;
  answer: string;
}

/** タップ用の選択肢(絵文字+短いことば) */
export interface TalkChoice {
  emoji: string;
  label: string;
}

export interface TalkNextRequest {
  history: TalkTurn[];
  answer?: {
    text?: string;
    audioBase64?: string;
    audioMime?: string;
  };
  failCount?: number;
}

export interface TalkNextResponse {
  answerText: string | null;
  retry: boolean;
  question: string;
  questionAudioBase64: string | null;
  questionAudioMime: string | null;
  choices: TalkChoice[];
  expression: FairyExpression;
  remaining: number;
  done: boolean;
}

export interface BookRequest {
  conversation: TalkTurn[];
}

export interface BookStartResponse {
  jobId: string;
}

export type BookJobStatus = 'story' | 'character' | 'pages' | 'audio' | 'done' | 'error';

export interface BookPageResult {
  text: string;
  imageBase64: string;
  imageMime: string;
  audioBase64: string | null;
  audioMime: string | null;
}

export interface BookJobResponse {
  status: BookJobStatus;
  progress: number;
  error?: string;
  result?: {
    title: string;
    characterRefBase64: string;
    characterRefMime: string;
    pages: BookPageResult[];
  };
}

/** 質問数の目安(進捗の花の数。サーバー側 QUESTION_TARGET と一致させる) */
export const QUESTION_TARGET = 5;

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${getTalkServerUrl()}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let message = `request failed (${res.status})`;
    try {
      const data = (await res.json()) as { error?: string };
      if (data.error) message = data.error;
    } catch {
      // JSON以外の応答は無視
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

/** 対話1ターン: 履歴+答えを送り、次の質問一式を受け取る */
export function talkNext(req: TalkNextRequest): Promise<TalkNextResponse> {
  return post<TalkNextResponse>('/api/talk/next', req);
}

/** 絵本生成ジョブを開始する */
export function startBookJob(conversation: TalkTurn[]): Promise<BookStartResponse> {
  return post<BookStartResponse>('/api/book', { conversation } satisfies BookRequest);
}

/** 絵本生成ジョブの状況を取得する */
export async function getBookJob(jobId: string): Promise<BookJobResponse> {
  const res = await fetch(`${getTalkServerUrl()}/api/book/${encodeURIComponent(jobId)}`);
  if (!res.ok) throw new Error(`job polling failed (${res.status})`);
  return (await res.json()) as BookJobResponse;
}

/** base64文字列をBlobに変換する(生成画像・音声の取り込み用) */
export function base64ToBlob(base64: string, mime: string): Blob {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

/** Blobをbase64文字列に変換する(録音音声の送信用) */
export function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = reader.result as string;
      resolve(url.slice(url.indexOf(',') + 1));
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}
