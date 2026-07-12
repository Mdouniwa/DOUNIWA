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
}

export interface Draft {
  theme: Theme;
  pages: DraftPage[];
  coverPageId: string | null;
  title: string;
}

export const MIN_PHOTOS = 5;
export const MAX_PHOTOS = 10;
