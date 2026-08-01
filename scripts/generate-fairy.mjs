/**
 * えほんの精(妖精キャラクター)の表情アセットを生成する開発時スクリプト。
 *
 * ランタイムでは生成せず、ここで作ったPNGを静的アセットとして同梱する
 * (ランタイムのAPI依存とコストをゼロにするため)。
 *
 * 手順:
 *   1枚目(normal)を基準画像として生成
 *   → 残りの表情は基準画像を「参照画像」として渡して生成(全表情で同一キャラクターに見せる)
 *
 * 実行方法(いずれか):
 *   GEMINI_API_KEY=... node scripts/generate-fairy.mjs
 *   GOOGLE_CLOUD_PROJECT=... GOOGLE_APPLICATION_CREDENTIALS=... node scripts/generate-fairy.mjs
 *
 * 出力: public/fairy/fairy-{normal,happy,thinking,surprised,cheer}.png (512x512)
 * モデル: IMAGE_MODEL 環境変数で差し替え可(既定: Nano Banana 2)
 */
import { GoogleGenAI } from '@google/genai';
import sharp from 'sharp';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const IMAGE_MODEL = process.env.IMAGE_MODEL || 'gemini-3.1-flash-image';
const OUT_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public', 'fairy');
const SIZE = 512;

// オリジナルキャラクターとしての基準デザイン。
// 既存の商業キャラクターに似せる指示は絶対に入れないこと(著作権・生成ガード対策)。
const CHARACTER = `オリジナルキャラクター「えほんの精」の全身イラスト。
手のひらに乗るくらい小さな妖精の女の子。清楚でやさしく、穏やかで親しみやすい雰囲気(派手さやコケティッシュさはない)。
背中に薄く光る半透明の羽。まわりにやわらかい光の粒がただよう。
色調はパステル(やわらかい水色のワンピース、白、淡い黄色の光)。ふんわりした淡い色の髪。
絵本の挿絵と調和する、温かみのある手描き風・丸みのあるやさしいタッチ。
背景は完全な透明または白1色。文字は入れない。子ども向け絵本アプリのキャラクター。`;

const EXPRESSIONS = [
  ['normal', 'おだやかにほほえんでいる、リラックスした立ち姿'],
  ['happy', 'とてもうれしそうに目を細めて笑い、両手を胸の前であわせている'],
  ['thinking', '人差し指をあごにあてて、少し上を見ながら考えている'],
  ['surprised', '目をまるくして、口を小さくあけておどろいている'],
  ['cheer', '両手を上にあげて、とびはねてよろこんでいる。まわりにキラキラの光'],
];

function makeClient() {
  if (process.env.GOOGLE_CLOUD_PROJECT) {
    return new GoogleGenAI({
      vertexai: true,
      project: process.env.GOOGLE_CLOUD_PROJECT,
      location: process.env.GOOGLE_CLOUD_LOCATION || 'global',
    });
  }
  if (process.env.GEMINI_API_KEY) {
    return new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
  }
  console.error(
    'GEMINI_API_KEY か GOOGLE_CLOUD_PROJECT+GOOGLE_APPLICATION_CREDENTIALS を設定してください',
  );
  process.exit(1);
}

function firstInlineData(resp) {
  for (const p of resp.candidates?.[0]?.content?.parts ?? []) {
    if (p.inlineData?.data) return p.inlineData;
  }
  return null;
}

async function generate(ai, prompt, referenceImage) {
  const parts = [];
  if (referenceImage) {
    parts.push({
      inlineData: { data: referenceImage.data, mimeType: referenceImage.mimeType || 'image/png' },
    });
    parts.push({
      text: `添付画像とまったく同じキャラクター(同じ顔、同じ髪、同じ服、同じ画風)で、ポーズと表情だけを変えて描いてください。\n${prompt}`,
    });
  } else {
    parts.push({ text: prompt });
  }
  const resp = await ai.models.generateContent({
    model: IMAGE_MODEL,
    contents: [{ role: 'user', parts }],
    config: { responseModalities: ['IMAGE'] },
  });
  const img = firstInlineData(resp);
  if (!img) throw new Error('画像が返りませんでした');
  return img;
}

async function savePng(name, img) {
  const buf = Buffer.from(img.data, 'base64');
  const out = await sharp(buf)
    .resize(SIZE, SIZE, { fit: 'contain', background: { r: 255, g: 255, b: 255, alpha: 0 } })
    .png()
    .toBuffer();
  const file = path.join(OUT_DIR, `fairy-${name}.png`);
  await writeFile(file, out);
  console.log(`✓ ${file}`);
}

const ai = makeClient();
await mkdir(OUT_DIR, { recursive: true });

// 1枚目 = 基準画像
const [baseName, basePose] = EXPRESSIONS[0];
console.log(`基準画像を生成中 (${baseName})...`);
const baseImage = await generate(ai, `${CHARACTER}\n表情とポーズ: ${basePose}`);
await savePng(baseName, baseImage);

// 2枚目以降 = 参照画像方式で同一キャラクターに揃える
for (const [name, pose] of EXPRESSIONS.slice(1)) {
  console.log(`参照画像方式で生成中 (${name})...`);
  const img = await generate(ai, `表情とポーズ: ${pose}`, baseImage);
  await savePng(name, img);
}

console.log('完了。public/fairy/ を確認してください。');
