# Design — しゃべるえほん

A locked design system for this app. Every page redesign reads this file before
emitting code. Do not regenerate per page — extend or amend this file when the
system needs to grow.

## Genre

playful(子ども・家族向け。ただし品位を保つ — 過剰な彩度・ザニーさは禁止)

## Vibe

「花畑・パステル・お姫さま・きらめき」— 桜ミルクの紙面にローズピンクを主役、
すみれラベンダー・ミント・ティアラゴールドを脇役に。装飾はCSSのみ(画像ファイル不使用)。
例外(v5): 「えほんの精」のキャラクター画像(`public/fairy/*.png`)のみ静的画像を許可。
パステル水色・白・淡黄でこのパレットと調和させること。

## Macrostructure family

既存のアプリ画面構成を保持する。UI層のみテーマ適用。

- Home:   2列グリッド(絵本棚メタファー)+ 角の花飾り
- Player: 全画面・宵の城空(deep plum)背景 + 見開きページ台紙
- Create: 対話(えほんの精)→ 生成 → 確認のフロー。確認以降は ProgressDots
- Parent: 管理リスト(実務優先・装飾控えめ)

## Theme (custom · tuned)

- `--color-bg`           oklch(96.5% 0.018 340)  桜ミルク
- `--color-card`         oklch(99% 0.006 340)    白(ほんのり桜)
- `--color-primary`      oklch(63% 0.16 350)     ローズピンク(主CTA)
- `--color-primary-dark` oklch(46% 0.14 350)     ベリー(見出し)
- `--color-accent`       oklch(58% 0.12 300)     すみれラベンダー
- `--color-green`        oklch(56% 0.09 165)     ミント
- `--color-red`          oklch(56% 0.17 15)      コーラル
- `--color-gold`         oklch(74% 0.11 85)      ティアラゴールド(装飾専用・文字下地に使わない)
- `--color-text`         oklch(30% 0.04 345)     深いプラム
- `--color-text-light`   oklch(50% 0.05 345)
- `--color-focus`        oklch(62% 0.19 350)     :focus-visible 専用

影・スピン(本の装丁)はプラム系 oklch(35% 0.08 340 / α) で統一。茶系rgbaは廃止。

## Typography

- Display/Body 共通: 'Hiragino Maru Gothic ProN' → 'BIZ UDGothic' → system-ui。
  オフライン完結PWAのため Web フォントは追加しない。丸ゴシックがこのテーマの
  ディスプレイ書体である(単一ファミリーはデザイン選択)。
- 見出し色は `--color-primary-dark`、本文は `--color-text`。
- イタリック見出し禁止(全ジャンル共通)。

## Spacing

既存の 4pt ベース(gap 8/12/16/20px)を維持。radius: `--radius-lg` 24px /
`--radius-md` 16px / 主ボタンは 999px ピル。

## Motion

- 既存アニメーション(ページめくり520ms・録音パルス・紙吹雪)は保持。
- v5追加(対話体験の中核として許可): 精のふわふわ浮遊/考え中スウェイ、
  マイク押下パルス、進捗の花の点灯、生成中の答え浮遊+進捗バー。
  いずれも `prefers-reduced-motion: reduce` で全停止(index.css のグローバルフォールバック)。
- 上記以外の新規モーションは追加しない。

## Microinteractions stance

- `.pressable`(押下で scale 0.95)が唯一の共通フィードバック。
- `:focus-visible` は `--color-focus` の 3px リング・出現アニメーションなし。
- celebratory は Done 画面の紙吹雪のみ(既存)。

## CTA voice

- Primary CTA: ローズピンク塗り + 白文字 + ピル形 + 内側上端ハイライト。
- Secondary: カード白地 + プラム文字(--ghost)。
- 破壊的操作: コーラル。子ども向けに最小 72px 高は維持。

## Per-page allowances

- Home / Create / Done: 角の花飾り・パステル背景テクスチャ可。
- Player: 装飾は星のきらめきドットのみ(読書の邪魔をしない)。
- Parent: 花飾りなし(保護者向け実務画面)。トークン色のみ適用。

## What pages MUST share

- トークン(色・radius・影)を必ず var() 参照。生の色値をCSSに直書きしない
  (透過が必要な場合は oklch(... / α) をトークン近傍の値で統一)。
- 丸ゴシックのフォントスタック。
- ボタンの最小タップ寸法(≥44px、主要は ≥72px)。

## What pages MAY differ on

- 背景の装飾密度(Player は夜空、他はパステル紙面)。
- 支援色の使い分け(green=完了/選択、accent=番号バッジ・副操作、red=削除/録音)。

## PWA chrome

- manifest `background_color: #fdf0f6` / `theme_color: #e27ba8`(index.html の
  `<meta name="theme-color">` と一致させること)。
