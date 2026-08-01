/**
 * えほんの精のプレースホルダーアセット生成(手作りSVG → PNG)。
 *
 * Nano Banana 2 での本生成(scripts/generate-fairy.mjs)には Google Cloud 認証が必要なため、
 * 認証を用意できない環境でもアプリが完全に動くように、同じファイル名・同じ5表情の
 * プレースホルダー画像を用意する。本生成を実行すると上書きされる。
 *
 * 実行: node scripts/fairy-placeholder.mjs
 * 出力: public/fairy/fairy-{normal,happy,thinking,surprised,cheer}.png (512x512, 透過)
 */
import sharp from 'sharp';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const OUT_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public', 'fairy');

const SKIN = '#fde8dc';
const HAIR = '#f6dfae';
const DRESS = '#cfe8f7';
const DRESS_DARK = '#b5d9ef';
const WING = '#e3f3fd';
const WING_EDGE = '#bfe3f7';
const BLUSH = '#f6c6c6';
const EYE = '#6b5b53';
const GLOW = '#fff7d9';
const SPARK = '#ffe9a8';

/** 4方向スパークル */
function spark(x, y, r, opacity = 0.9) {
  return `<path d="M ${x} ${y - r} Q ${x + r * 0.18} ${y - r * 0.18} ${x + r} ${y} Q ${x + r * 0.18} ${y + r * 0.18} ${x} ${y + r} Q ${x - r * 0.18} ${y + r * 0.18} ${x - r} ${y} Q ${x - r * 0.18} ${y - r * 0.18} ${x} ${y - r} Z" fill="${SPARK}" opacity="${opacity}"/>`;
}

function particles(seed) {
  const pts = [
    [96, 150], [418, 130], [70, 300], [440, 310], [120, 420], [400, 430], [210, 80], [330, 70],
  ];
  return pts
    .map(
      ([x, y], i) =>
        `<circle cx="${x + ((seed * 7 + i * 13) % 18) - 9}" cy="${y + ((seed * 11 + i * 5) % 14) - 7}" r="${4 + ((i + seed) % 3) * 2}" fill="${GLOW}" opacity="${0.5 + ((i + seed) % 3) * 0.15}"/>`,
    )
    .join('');
}

/** 目・口・眉・腕を表情ごとに差し替える */
const FACES = {
  normal: {
    eyes: `<circle cx="226" cy="208" r="9" fill="${EYE}"/><circle cx="286" cy="208" r="9" fill="${EYE}"/>
           <circle cx="229" cy="204" r="3" fill="#fff"/><circle cx="289" cy="204" r="3" fill="#fff"/>`,
    mouth: `<path d="M 244 238 Q 256 248 268 238" stroke="${EYE}" stroke-width="5" fill="none" stroke-linecap="round"/>`,
    arms: `<path d="M 216 320 Q 196 350 202 382" stroke="${SKIN}" stroke-width="18" fill="none" stroke-linecap="round"/>
           <path d="M 296 320 Q 316 350 310 382" stroke="${SKIN}" stroke-width="18" fill="none" stroke-linecap="round"/>`,
    extra: '',
  },
  happy: {
    eyes: `<path d="M 214 210 Q 226 198 238 210" stroke="${EYE}" stroke-width="7" fill="none" stroke-linecap="round"/>
           <path d="M 274 210 Q 286 198 298 210" stroke="${EYE}" stroke-width="7" fill="none" stroke-linecap="round"/>`,
    mouth: `<path d="M 240 234 Q 256 254 272 234 Z" fill="#e8907e"/>`,
    arms: `<path d="M 216 320 Q 232 344 248 350" stroke="${SKIN}" stroke-width="18" fill="none" stroke-linecap="round"/>
           <path d="M 296 320 Q 280 344 264 350" stroke="${SKIN}" stroke-width="18" fill="none" stroke-linecap="round"/>
           <circle cx="256" cy="352" r="13" fill="${SKIN}"/>`,
    extra: `${spark(360, 160, 16)}${spark(150, 175, 12)}`,
  },
  thinking: {
    eyes: `<circle cx="220" cy="200" r="9" fill="${EYE}"/><circle cx="280" cy="200" r="9" fill="${EYE}"/>
           <circle cx="222" cy="195" r="3" fill="#fff"/><circle cx="282" cy="195" r="3" fill="#fff"/>`,
    mouth: `<circle cx="254" cy="240" r="7" fill="#e8907e"/>`,
    arms: `<path d="M 216 320 Q 196 350 202 382" stroke="${SKIN}" stroke-width="18" fill="none" stroke-linecap="round"/>
           <path d="M 296 322 Q 314 300 296 262" stroke="${SKIN}" stroke-width="18" fill="none" stroke-linecap="round"/>
           <circle cx="292" cy="254" r="11" fill="${SKIN}"/>`,
    extra: `<circle cx="352" cy="128" r="7" fill="${GLOW}"/><circle cx="374" cy="104" r="10" fill="${GLOW}"/><circle cx="402" cy="76" r="13" fill="${GLOW}"/>`,
  },
  surprised: {
    eyes: `<circle cx="226" cy="206" r="13" fill="#fff" stroke="${EYE}" stroke-width="4"/><circle cx="286" cy="206" r="13" fill="#fff" stroke="${EYE}" stroke-width="4"/>
           <circle cx="226" cy="208" r="6" fill="${EYE}"/><circle cx="286" cy="208" r="6" fill="${EYE}"/>
           <path d="M 212 182 Q 226 174 240 182" stroke="${EYE}" stroke-width="5" fill="none" stroke-linecap="round"/>
           <path d="M 272 182 Q 286 174 300 182" stroke="${EYE}" stroke-width="5" fill="none" stroke-linecap="round"/>`,
    mouth: `<ellipse cx="256" cy="242" rx="10" ry="13" fill="#e8907e"/>`,
    arms: `<path d="M 216 320 Q 190 336 184 366" stroke="${SKIN}" stroke-width="18" fill="none" stroke-linecap="round"/>
           <path d="M 296 320 Q 322 336 328 366" stroke="${SKIN}" stroke-width="18" fill="none" stroke-linecap="round"/>`,
    extra: `${spark(388, 140, 20)}${spark(128, 150, 13)}`,
  },
  cheer: {
    eyes: `<path d="M 214 208 Q 226 196 238 208" stroke="${EYE}" stroke-width="7" fill="none" stroke-linecap="round"/>
           <path d="M 274 208 Q 286 196 298 208" stroke="${EYE}" stroke-width="7" fill="none" stroke-linecap="round"/>`,
    mouth: `<path d="M 236 232 Q 256 258 276 232 Z" fill="#e8907e"/>`,
    arms: `<path d="M 218 318 Q 186 292 176 254" stroke="${SKIN}" stroke-width="18" fill="none" stroke-linecap="round"/>
           <path d="M 294 318 Q 326 292 336 254" stroke="${SKIN}" stroke-width="18" fill="none" stroke-linecap="round"/>
           <circle cx="174" cy="248" r="11" fill="${SKIN}"/><circle cx="338" cy="248" r="11" fill="${SKIN}"/>`,
    extra: `${spark(150, 120, 16)}${spark(370, 110, 20)}${spark(410, 220, 12)}${spark(100, 230, 12)}`,
  },
};

function fairySvg(expr) {
  const f = FACES[expr];
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <!-- 後光 -->
  <circle cx="256" cy="256" r="190" fill="${GLOW}" opacity="0.45"/>
  <circle cx="256" cy="256" r="140" fill="${GLOW}" opacity="0.5"/>
  ${particles(expr.length)}
  <!-- 羽(背面) -->
  <g opacity="0.85">
    <ellipse cx="166" cy="270" rx="64" ry="96" fill="${WING}" stroke="${WING_EDGE}" stroke-width="4" transform="rotate(18 166 270)"/>
    <ellipse cx="346" cy="270" rx="64" ry="96" fill="${WING}" stroke="${WING_EDGE}" stroke-width="4" transform="rotate(-18 346 270)"/>
    <ellipse cx="182" cy="352" rx="38" ry="56" fill="${WING}" stroke="${WING_EDGE}" stroke-width="3" transform="rotate(30 182 352)"/>
    <ellipse cx="330" cy="352" rx="38" ry="56" fill="${WING}" stroke="${WING_EDGE}" stroke-width="3" transform="rotate(-30 330 352)"/>
  </g>
  <!-- ワンピース -->
  <path d="M 256 296 L 198 434 Q 256 456 314 434 Z" fill="${DRESS}"/>
  <path d="M 198 434 Q 256 456 314 434 L 314 442 Q 256 464 198 442 Z" fill="${DRESS_DARK}"/>
  <!-- 腕 -->
  ${f.arms}
  <!-- 脚 -->
  <path d="M 238 448 L 238 476" stroke="${SKIN}" stroke-width="16" stroke-linecap="round"/>
  <path d="M 274 448 L 274 476" stroke="${SKIN}" stroke-width="16" stroke-linecap="round"/>
  <!-- 首・体 -->
  <rect x="240" y="272" width="32" height="40" rx="14" fill="${SKIN}"/>
  <!-- 頭 -->
  <circle cx="256" cy="210" r="86" fill="${SKIN}"/>
  <!-- 髪 -->
  <path d="M 170 210 Q 168 118 256 116 Q 344 118 342 210 Q 344 176 322 158 Q 336 196 318 178 Q 300 148 256 148 Q 212 148 194 178 Q 176 196 190 158 Q 168 176 170 210 Z" fill="${HAIR}"/>
  <path d="M 172 208 Q 160 262 176 296 Q 190 268 186 224 Z" fill="${HAIR}"/>
  <path d="M 340 208 Q 352 262 336 296 Q 322 268 326 224 Z" fill="${HAIR}"/>
  <path d="M 244 120 Q 256 96 272 118 Q 262 112 254 122 Z" fill="${HAIR}"/>
  <!-- ほっぺ -->
  <circle cx="204" cy="236" r="12" fill="${BLUSH}" opacity="0.65"/>
  <circle cx="308" cy="236" r="12" fill="${BLUSH}" opacity="0.65"/>
  <!-- 顔 -->
  ${f.eyes}
  ${f.mouth}
  ${f.extra}
</svg>`;
}

await mkdir(OUT_DIR, { recursive: true });
for (const expr of Object.keys(FACES)) {
  const png = await sharp(Buffer.from(fairySvg(expr))).resize(512, 512).png().toBuffer();
  const file = path.join(OUT_DIR, `fairy-${expr}.png`);
  await writeFile(file, png);
  console.log(`✓ ${file}`);
}
console.log('プレースホルダー生成完了(本生成: node scripts/generate-fairy.mjs)');
