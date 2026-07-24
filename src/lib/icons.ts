/**
 * 子どもが絵本の素材として選ぶアイコンのプール。
 * emojiをそのまま絵として使う(画像ファイル不要)。keywordは物語生成APIに渡す。
 */

export type IconCategory = 'animal' | 'vehicle' | 'food' | 'place' | 'weather';

export interface IconDef {
  keyword: string; // 物語生成に渡す日本語のことば
  emoji: string;
  category: IconCategory;
}

export const ICON_POOL: IconDef[] = [
  // どうぶつ
  { keyword: 'ぞう', emoji: '🐘', category: 'animal' },
  { keyword: 'いぬ', emoji: '🐶', category: 'animal' },
  { keyword: 'ねこ', emoji: '🐱', category: 'animal' },
  { keyword: 'うさぎ', emoji: '🐰', category: 'animal' },
  { keyword: 'くま', emoji: '🐻', category: 'animal' },
  { keyword: 'ぱんだ', emoji: '🐼', category: 'animal' },
  // のりもの
  { keyword: 'でんしゃ', emoji: '🚃', category: 'vehicle' },
  { keyword: 'くるま', emoji: '🚗', category: 'vehicle' },
  { keyword: 'ひこうき', emoji: '✈️', category: 'vehicle' },
  { keyword: 'ふね', emoji: '⛵', category: 'vehicle' },
  { keyword: 'バス', emoji: '🚌', category: 'vehicle' },
  // たべもの
  { keyword: 'りんご', emoji: '🍎', category: 'food' },
  { keyword: 'ケーキ', emoji: '🍰', category: 'food' },
  { keyword: 'パン', emoji: '🍞', category: 'food' },
  { keyword: 'アイス', emoji: '🍦', category: 'food' },
  // ばしょ
  { keyword: 'こうえん', emoji: '🏞️', category: 'place' },
  { keyword: 'おうち', emoji: '🏠', category: 'place' },
  { keyword: 'うみ', emoji: '🌊', category: 'place' },
  { keyword: 'やま', emoji: '⛰️', category: 'place' },
  // てんき
  { keyword: 'あめ', emoji: '☂️', category: 'weather' },
  { keyword: 'にじ', emoji: '🌈', category: 'weather' },
  { keyword: 'おひさま', emoji: '☀️', category: 'weather' },
];

const BY_KEYWORD: Record<string, IconDef> = Object.fromEntries(
  ICON_POOL.map((i) => [i.keyword, i]),
);

export function iconByKeyword(keyword: string): IconDef | undefined {
  return BY_KEYWORD[keyword];
}

export function iconEmoji(keyword: string): string {
  return BY_KEYWORD[keyword]?.emoji ?? '⭐';
}

/** 選択キーワードから絵本のテーマ(既存Book.theme用)を推定 */
export function categoryToTheme(category: IconCategory): 'odekake' | 'birthday' | 'animal' | 'vehicle' {
  switch (category) {
    case 'animal':
      return 'animal';
    case 'vehicle':
      return 'vehicle';
    case 'food':
      return 'birthday';
    default:
      return 'odekake';
  }
}
