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
}

export interface Page {
  id: string;
  bookId: string;
  imageBlob: Blob; // 長辺1500px, JPEG quality 0.82
  thumbBlob: Blob; // 長辺300px
  captionText: string;
  audioBlob: Blob | null;
  audioMime: string | null;
  soundEffect: SoundEffect | null;
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
