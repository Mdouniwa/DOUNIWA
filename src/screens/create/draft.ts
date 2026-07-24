import type { SoundEffect, Theme } from '../../types';

/** 作成フロー中の下書きページ(保存前はメモリ上に保持) */
export interface DraftPage {
  id: string;
  imageBlob: Blob;
  thumbBlob: Blob;
  captionText: string;
  audioBlob: Blob | null;
  audioMime: string | null;
  soundEffect: SoundEffect | null;
  // 音声の出自: AI生成か、子どもの録音で上書きされたか
  narrationSource?: 'generated' | 'recorded';
}

export interface Draft {
  theme: Theme;
  pages: DraftPage[];
  coverPageId: string | null;
  title: string;
  iconKeywords: string[]; // 選んだ5つのアイコンキーワード(選択順)
}
