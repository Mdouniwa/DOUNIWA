// アイコンPNG生成スクリプト: node scripts/generate-icons.mjs
// scripts/icon.svg から PWA 用アイコン一式を public/ に出力する
import sharp from 'sharp';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const src = join(root, 'scripts', 'icon.svg');
const out = join(root, 'public');
await mkdir(out, { recursive: true });

// 通常アイコン(角丸込みの絵をそのまま)
for (const size of [192, 512]) {
  await sharp(src).resize(size, size).png().toFile(join(out, `icon-${size}.png`));
}

// apple-touch-icon はiOSが角丸を付けるため、背景を敷いた正方形にする
const appleBase = await sharp({
  create: { width: 512, height: 512, channels: 4, background: '#ffb300' },
})
  .composite([{ input: await sharp(src).resize(448, 448).png().toBuffer() }])
  .png()
  .toBuffer();
await sharp(appleBase).resize(180, 180).png().toFile(join(out, 'apple-touch-icon.png'));

// maskable: セーフゾーン確保のため80%に縮小して背景色で埋める
await sharp({
  create: { width: 512, height: 512, channels: 4, background: '#ffb300' },
})
  .composite([{ input: await sharp(src).resize(410, 410).png().toBuffer() }])
  .png()
  .toFile(join(out, 'icon-maskable-512.png'));

console.log('icons generated in public/');
