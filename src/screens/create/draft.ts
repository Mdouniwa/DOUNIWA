import type { SoundEffect, Theme } from '../../types';
import type { TalkTurn } from '../../lib/talkApi';

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
  /** えほんの精との対話ログ(物語の材料) */
  conversation: TalkTurn[];
  /** 主人公の基準画像(参照画像方式の1枚目)。保存時にpageIds外のPageとして格納する */
  characterRef: { imageBlob: Blob; thumbBlob: Blob } | null;
}
