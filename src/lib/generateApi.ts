/**
 * `/api/generate-book` の入出力契約(クライアント・サーバー共通)。
 * サーバー(api/generate-book.ts)はVercel側で別バンドルされるため、
 * この型定義を「唯一の契約」として両者が参照する。
 */

/** 生成リクエスト: 選択順の5つのアイコンキーワード */
export interface GenerateBookRequest {
  icons: string[];
}

/** 生成された1ページ分(画像・音声はbase64) */
export interface GeneratedPage {
  text: string;
  imageBase64: string;
  imageMime: string; // 例: 'image/png'
  audioBase64: string | null; // 音声生成に失敗した場合はnull(クライアントでTTSフォールバック)
  audioMime: string | null; // 例: 'audio/wav'
}

/** 生成レスポンス */
export interface GenerateBookResponse {
  title: string;
  pages: GeneratedPage[];
}

/** エラーレスポンス */
export interface GenerateBookError {
  error: string;
}

/** 選択するアイコン数(物語のページ数の元) */
export const ICON_COUNT = 5;
