export type Theme = 'odekake' | 'birthday' | 'animal' | 'vehicle';

export type SoundEffect = 'clap' | 'animal' | 'car' | 'sparkle' | 'trumpet';

/** UIフィードバック音も含めた合成音の種類 */
export type SynthSound = SoundEffect | 'tap' | 'success';

export interface Book {
  id: string;
  title: string;
  coverImageId: string | null; // 表紙に使うPageのid
  theme: Theme;
  pageIds: string[]; // ページ順序はこの配列が唯一の真実
  createdAt: number;
  updatedAt: number;
  lastOpenedAt: number;
  // v4: 選んだ5つのアイコンキーワード(選択順)。旧データ互換のため残す
  iconKeywords?: string[];
  // v5: えほんの精との対話ログ(iconKeywordsを置き換え)。旧データには無いためoptional
  conversation?: Array<{ question: string; answer: string }>;
  // v5: 主人公の基準画像のPage id(参照画像方式用。pageIdsには含めない)
  characterRefImageId?: string;
}

export interface Page {
  id: string;
  bookId: string;
  imageBlob: Blob; // AI生成挿絵(長辺1500px JPEG)。旧・写真絵本では家族写真
  thumbBlob: Blob; // 長辺300px
  captionText: string; // AI生成した物語文。旧・写真絵本では親の手入力
  audioBlob: Blob | null;
  audioMime: string | null;
  soundEffect: SoundEffect | null;
  // 音声の出自: 'generated'=AI生成 / 'recorded'=子どもの録音で上書き。
  // 旧データには無いためoptional(未設定でも audioBlob があればそれを再生する)
  narrationSource?: 'generated' | 'recorded';
}

export interface Settings {
  autoPlayOn: boolean; // default true
  narrationMode: 'recorded' | 'tts'; // default 'recorded'
  bgmOn: boolean; // default false, MVPではUI非露出
}

export const DEFAULT_SETTINGS: Settings = {
  autoPlayOn: true,
  narrationMode: 'recorded',
  bgmOn: false,
};

export const THEME_LABELS: Record<Theme, string> = {
  odekake: 'きょうのおでかけ',
  birthday: 'おたんじょうび',
  animal: 'どうぶつ',
  vehicle: 'のりもの',
};

export const THEME_EMOJI: Record<Theme, string> = {
  odekake: '🌄',
  birthday: '🎂',
  animal: '🐰',
  vehicle: '🚗',
};

export const SOUND_EFFECT_LABELS: Record<SoundEffect, string> = {
  clap: 'はくしゅ',
  animal: 'どうぶつ',
  car: 'くるま',
  sparkle: 'キラキラ',
  trumpet: 'ラッパ',
};

export const SOUND_EFFECT_EMOJI: Record<SoundEffect, string> = {
  clap: '👏',
  animal: '🐶',
  car: '🚗',
  sparkle: '✨',
  trumpet: '🎺',
};
