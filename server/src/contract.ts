/**
 * PWAクライアントとの入出力契約。
 * クライアント側の src/lib/talkApi.ts と必ず一致させること(既存の generateApi.ts と同じ方針で、
 * サーバーは別パッケージのため型はここに自己完結で定義する)。
 */

/** えほんの精の表情(静的アセットのファイル名と対応) */
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

/** 対話リクエスト: 履歴 + 今回の答え(テキスト or 録音音声)。答え無しなら最初の質問を返す */
export interface TalkNextRequest {
  history: TalkTurn[];
  answer?: {
    text?: string;
    audioBase64?: string;
    audioMime?: string;
  };
  /** 連続で聞き取れなかった回数(3回目以降は選択肢誘導を強める) */
  failCount?: number;
}

export interface TalkNextResponse {
  /** 音声だった場合にAIが解釈した答え(テキスト回答ならそのまま)。聞き取れなければ null */
  answerText: string | null;
  /** 聞き取れなかった場合 true(質問は聞き返しになる) */
  retry: boolean;
  /** 精のせりふ(相槌+次の質問、または聞き返し) */
  question: string;
  /** 質問の読み上げ音声(WAV base64)。TTS失敗時は null → クライアントでWeb Speechにフォールバック */
  questionAudioBase64: string | null;
  questionAudioMime: string | null;
  choices: TalkChoice[];
  expression: FairyExpression;
  /** 残りの質問数の目安(進捗表示用) */
  remaining: number;
  /** 対話が完了し、絵本生成に進める状態 */
  done: boolean;
}

/** 絵本生成リクエスト: 対話ログ全体 */
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
  /** 生成の進み具合(0〜1)。生成中画面の演出用 */
  progress: number;
  error?: string;
  result?: {
    title: string;
    /** 主人公の基準画像(参照画像方式の1枚目)。クライアントで保存して再生成に使える */
    characterRefBase64: string;
    characterRefMime: string;
    pages: BookPageResult[];
  };
}

export interface ApiError {
  error: string;
}
