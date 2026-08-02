/**
 * v6 生成済みアート素材のパス集約。
 * 素材は scripts/generate-art.mjs で開発時に生成した静的アセット
 * (ランタイムでのAPI呼び出しはゼロ)。パスのハードコード重複を防ぐため必ずここを参照する。
 */
import type { FairyExpression } from './talkApi';

/** えほんの精の表情画像(TalkScreen / Generating 共用) */
export const FAIRY_IMAGES: Record<FairyExpression, string> = {
  normal: '/fairy/fairy-normal.png',
  happy: '/fairy/fairy-happy.png',
  thinking: '/fairy/fairy-thinking.png',
  surprised: '/fairy/fairy-surprised.png',
  cheer: '/fairy/fairy-cheer.png',
};

export const ART = {
  logo: '/art/logo.png',
  bgHome: '/art/bg-home.webp',
  bgTalk: '/art/bg-talk.webp',
  frameBook: '/art/frame-book.png',
  buttonPlate: '/art/button-plate.png',
} as const;

export type DecoName =
  | 'elephant'
  | 'rabbit'
  | 'bear'
  | 'bird'
  | 'fox'
  | 'train'
  | 'balloon'
  | 'ship'
  | 'mushroom'
  | 'tree'
  | 'star'
  | 'rainbow'
  | 'cloud'
  | 'flower';

/** 装飾イラスト(public/art/deco/)のパス */
export const deco = (name: DecoName): string => `/art/deco/${name}.png`;
