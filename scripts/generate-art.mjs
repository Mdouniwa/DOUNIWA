/**
 * v6 アート素材(3Dレンダリング調)を一括生成する開発時スクリプト。
 *
 * ランタイムでは生成せず、ここで作った画像を静的アセットとして同梱する
 * (ランタイムのAPI依存とコストをゼロにするため)。
 *
 * 生成対象:
 *   fairy : public/fairy/fairy-{normal,happy,thinking,surprised,cheer}.png
 *           (1枚目を基準画像に、残りは参照画像方式で同一キャラクター化)
 *   logo  : public/art/logo.png
 *   bg    : public/art/bg-{home,talk}.webp
 *   deco  : public/art/deco/*.png (14点)
 *   ui    : public/art/frame-book.png, public/art/button-plate.png
 *
 * 実行方法:
 *   node --env-file="$HOME/.ehon-art.env" scripts/generate-art.mjs
 *   (GEMINI_API_KEY=... を含む env ファイル。直接 GEMINI_API_KEY=... node ... でも可)
 *
 * オプション:
 *   --only=fairy,bg   指定グループだけ生成(fairy|logo|bg|deco|ui)
 *   --force           既存ファイルがあっても再生成(既定はスキップ)
 *
 * 途中失敗しても既存アセットを壊さないよう、一時ディレクトリ(.tmp-art/)に
 * 書き出してから1点ずつ完成時に本来の場所へ移動する。
 *
 * モデル: IMAGE_MODEL 環境変数で差し替え可(既定: Nano Banana 2 = gemini-3.1-flash-image)
 */
import { GoogleGenAI } from '@google/genai';
import sharp from 'sharp';
import { mkdir, rename, writeFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const IMAGE_MODEL = process.env.IMAGE_MODEL || 'gemini-3.1-flash-image';
const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const TMP_DIR = path.join(ROOT, '.tmp-art');
const PUBLIC = path.join(ROOT, 'public');

// ---------------------------------------------------------------------------
// アートディレクション(全素材共通)
// ---------------------------------------------------------------------------

const STYLE = `高品質な3Dレンダリング調(3DCGアニメ映画風)のイラスト。
やわらかい質感、あたたかいライティング。ファンタジー絵本の世界観。
明るく彩度は高めだが上品で、緑・金色・淡い青を基調にした配色。
子ども向けなので、怖さ・暗さ・鋭さのある表現は一切なし。文字は入れない。`;

// 透過が必要な素材はマゼンタ単色背景で生成し、後段のクロマキー処理で抜く。
// (モデルがアルファ付きPNGを返した場合はそのまま使う)
const CHROMA_BG = `背景は完全に一様なマゼンタ1色(#FF00FF)で塗りつぶすこと。
背景に模様・グラデーション・影・光の演出を入れない。被写体にはマゼンタ色を一切使わない。`;

// オリジナルキャラクター「えほんの精」。
// 既存の商業キャラクターに似せる指示は絶対に入れないこと(著作権・生成ガード対策)。
const CHARACTER = `オリジナルキャラクター「えほんの精」の全身イラスト。
森に住む若い女性の妖精。6〜7頭身のリアル寄りの体型。
肌は磁器のように白く、内側からほのかに光るような透明感のある質感。血色や頬の赤みは最小限。
目は切れ長のアーモンド型で、涼しげで知的な目元(大きく見開いた丸い目にしない)。
輪郭は細面で、顎のラインがすっきりした面長(丸顔にしない)。
長くつややかなブロンドの髪、エルフのように先のとがった耳。
全体に儚げで神秘的な雰囲気。静かで少し憂いのある、清楚で品のある佇まい
(健康的で快活な印象にはしない)。
衣装は淡い緑と白を基調とした上品なローブ風のドレスで、露出を抑えた健全なデザイン
(子ども向けアプリの案内役として適切であること)。
背中に薄く透ける光の羽。まわりに金色の小さな光の粒。
頭のてっぺんからつま先まで全身がフレームに入る構図。`;

const EXPRESSIONS = [
  ['normal', '静かにやわらかく微笑んで、リラックスして立っている。儚げで神秘的な雰囲気'],
  [
    'happy',
    'うれしそうに目を細めてあたたかく微笑み、両手を胸の前で軽くあわせている。この表情では儚さよりも温かさと親しみやすさを前面に出す',
  ],
  ['thinking', '人差し指をあごにあて、少し首をかしげて考えている。物静かで知的な雰囲気'],
  ['surprised', '切れ長の目を少し見開き、口を小さくあけて上品におどろいている'],
  [
    'cheer',
    '両手を高く挙げてにこやかに応援している。まわりにキラキラの光。この表情では儚さよりも温かさと親しみやすさを前面に出す',
  ],
];

// ---------------------------------------------------------------------------
// 素材マニフェスト
// ---------------------------------------------------------------------------

const DECO = [
  ['elephant', 'かわいい子どものぞう。丸みのあるフォルム、やさしい笑顔'],
  ['rabbit', 'かわいい子うさぎ。ふわふわの毛、長い耳、やさしい笑顔'],
  ['bear', 'かわいい子ぐま。丸みのあるフォルム、はちみつ色の毛、やさしい笑顔'],
  ['bird', 'かわいいことり。丸いからだ、明るい水色と黄色の羽'],
  ['fox', 'かわいい子ぎつね。丸みのあるフォルム、ふさふさのしっぽ、やさしい笑顔'],
  ['train', 'かわいいおもちゃの汽車。丸みのあるフォルム、緑と金色の装飾'],
  ['balloon', 'かわいい気球。丸みのあるフォルム、淡い緑と金色と白のストライプ'],
  ['ship', 'かわいいおもちゃの帆船。丸みのあるフォルム、白い帆、木の船体'],
  ['mushroom', 'かわいいきのこ。赤い傘に白い水玉、丸みのあるフォルム'],
  ['tree', '大きくてやさしい雰囲気の木。丸い緑の葉、金色の木漏れ日の光の粒'],
  ['star', 'きらきら光るかわいい星。金色でぷっくりした立体感'],
  ['rainbow', 'かわいい虹。パステル色、両端に小さな白い雲'],
  ['cloud', 'ふわふわのかわいい白い雲。丸みのあるフォルム'],
  ['flower', 'かわいい花。淡いピンクと白の花びら、金色の中心'],
];

/**
 * @typedef {Object} Asset
 * @property {string} id       表示用ID
 * @property {string} group    fairy|logo|bg|deco|ui
 * @property {string} out      PUBLIC からの相対出力パス
 * @property {string} prompt   生成プロンプト(STYLE は自動で付与)
 * @property {boolean} transparent 透過が必要か(クロマキー処理対象)
 * @property {string} aspect   生成時のアスペクト比
 * @property {[number, number]} size リサイズ後の [幅, 高さ]
 * @property {'png'|'webp'} format
 */

/** @type {Asset[]} */
const ASSETS = [
  // --- fairy(参照画像方式のため runFairy() で特別扱い) ---
  ...EXPRESSIONS.map(([name, pose]) => ({
    id: `fairy-${name}`,
    group: 'fairy',
    out: `fairy/fairy-${name}.png`,
    prompt: pose,
    transparent: true,
    aspect: '3:4',
    size: [512, 512],
    format: 'png',
  })),

  // --- logo ---
  {
    id: 'logo',
    group: 'logo',
    out: 'art/logo.png',
    prompt: `「しゃべるえほん」という日本語(ひらがな6文字)の立体的な描き文字ロゴ。
ぷっくりとした3D調の文字、金色の縁取り、光沢のあるつややかな質感。
文字のまわりに小さな葉っぱと金色の光の粒の飾り。
文字は「しゃべるえほん」以外を絶対に入れない。正確なひらがなで描くこと。`,
    transparent: true,
    aspect: '16:9',
    size: [1024, 576],
    format: 'png',
  },

  // --- 背景 ---
  {
    id: 'bg-home',
    group: 'bg',
    out: 'art/bg-home.webp',
    prompt: `ファンタジー絵本の森の風景。1枚の連続したワイドな風景画。
明るい森と青空、木々の間から差し込む木漏れ日、ただよう金色の光の粒、遠景に淡い虹。
被写界深度のあるやわらかいボケ。
画面の中央〜下部は開けた明るい草地。虹などの重要な要素は画面の中央付近に配置する。
分割・コマ割り・コラージュにせず、必ず1枚のつながった風景として描くこと。
アプリのホーム画面の背景に使うので、全体的にやわらかく、うるさくならないこと。`,
    transparent: false,
    aspect: '16:9',
    size: [1600, 900],
    format: 'webp',
  },
  {
    id: 'bg-talk',
    group: 'bg',
    out: 'art/bg-talk.webp',
    prompt: `ファンタジー絵本の森の風景。背景アート。
明るい森、木々の間から差し込む木漏れ日、ただよう金色の光の粒。
被写界深度のある大きくやわらかいボケ。
画面中央がやや明るく開けていて、中央に立つキャラクターが映える構図
(中央に人物は描かない。風景のみ)。重要な要素は中央に寄せる。
アプリの対話画面の背景に使うので、全体的にやわらかく、うるさくならないこと。`,
    transparent: false,
    aspect: '16:9',
    size: [1600, 900],
    format: 'webp',
  },

  // --- 装飾イラスト ---
  ...DECO.map(([name, desc]) => ({
    id: `deco-${name}`,
    group: 'deco',
    out: `art/deco/${name}.png`,
    prompt: `${desc}。子ども向け絵本アプリの画面に散りばめる小さな装飾イラスト。1つだけ描く。`,
    transparent: true,
    aspect: '1:1',
    size: [320, 320],
    format: 'png',
  })),

  // --- UIパーツ ---
  {
    id: 'frame-book',
    group: 'ui',
    out: 'art/frame-book.png',
    prompt: `絵本カード用の正方形の装飾フレーム(額縁)。
細い木の枝と蔦、緑の葉、小さな花と金色の光の粒のモチーフで四辺を囲む。
上下左右が対称に近く、四隅と辺を分割して使えるデザイン(9-slice用)。
フレームの中央は完全に空(背景色のみ)にして、何も描かない。`,
    transparent: true,
    aspect: '1:1',
    size: [768, 768],
    format: 'png',
  },
  {
    id: 'scroll',
    group: 'ui',
    out: 'art/scroll.png',
    prompt: `横長の巻物(スクロール)。少し開いた羊皮紙風の紙、あたたかい淡いクリーム色。
左右の両端に丸い木の軸。縁に沿って緑の小さな蔦の葉と金色の光の粒の控えめな飾り。
中央は無地で、あとから文字を載せられるように空けておく。
上下左右の縁の飾りは対称に近く、9-sliceで分割して使えるデザイン。`,
    transparent: true,
    aspect: '21:9',
    size: [640, 274],
    format: 'png',
  },
  {
    id: 'button-plate',
    group: 'ui',
    out: 'art/button-plate.png',
    prompt: `横長の木製看板風のボタンプレート。
角の丸い横長の板。立体的な厚みと、明るくあたたかい色の木目。
縁に沿って小さな緑の葉と金色の光の粒の控えめな飾り。
中央は無地で、あとから文字を載せられるように空けておく。`,
    transparent: true,
    aspect: '21:9',
    size: [640, 274],
    format: 'png',
  },
];

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

const argv = process.argv.slice(2);
const force = argv.includes('--force');
const onlyArg = argv.find((a) => a.startsWith('--only='));
const only = onlyArg ? onlyArg.slice('--only='.length).split(',').filter(Boolean) : null;
const KNOWN_GROUPS = ['fairy', 'logo', 'bg', 'deco', 'ui'];
if (only) {
  const bad = only.filter((g) => !KNOWN_GROUPS.includes(g));
  if (bad.length) {
    console.error(`不明なグループ: ${bad.join(', ')}(有効: ${KNOWN_GROUPS.join('|')})`);
    process.exit(1);
  }
}
const inScope = (asset) => !only || only.includes(asset.group);

// ---------------------------------------------------------------------------
// 生成 API
// ---------------------------------------------------------------------------

function makeClient() {
  if (!process.env.GEMINI_API_KEY) {
    console.error(
      'GEMINI_API_KEY を設定してください(例: node --env-file="$HOME/.ehon-art.env" scripts/generate-art.mjs)',
    );
    process.exit(1);
  }
  return new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
}

function firstInlineData(resp) {
  for (const p of resp.candidates?.[0]?.content?.parts ?? []) {
    if (p.inlineData?.data) return p.inlineData;
  }
  return null;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let generatedCount = 0;

async function generate(ai, prompt, aspect, referenceImage) {
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
  let lastErr;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const resp = await ai.models.generateContent({
        model: IMAGE_MODEL,
        contents: [{ role: 'user', parts }],
        config: {
          responseModalities: ['IMAGE'],
          imageConfig: { aspectRatio: aspect },
        },
      });
      const img = firstInlineData(resp);
      if (!img) throw new Error('画像が返りませんでした');
      generatedCount++;
      return img;
    } catch (err) {
      lastErr = err;
      if (attempt < 3) {
        const wait = attempt * 5000;
        console.warn(`  リトライ ${attempt}/2(${wait / 1000}s 待機): ${err.message ?? err}`);
        await sleep(wait);
      }
    }
  }
  throw lastErr;
}

// ---------------------------------------------------------------------------
// 画像処理(クロマキー除去・リサイズ・圧縮)
// ---------------------------------------------------------------------------

/** 返却画像に実質的なアルファがあるか */
async function hasRealAlpha(buf) {
  const meta = await sharp(buf).metadata();
  if (!meta.hasAlpha) return false;
  const stats = await sharp(buf).stats();
  const alpha = stats.channels[stats.channels.length - 1];
  return alpha.min < 250;
}

/** マゼンタ背景をクロマキーで抜く(スピル除去つき) */
async function chromaKey(buf) {
  const { data, info } = await sharp(buf)
    .ensureAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const LO = 32; // これ以下のマゼンタ度は被写体として残す
  const HI = 110; // これ以上のマゼンタ度は完全透過
  for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    const m = Math.min(r, b) - g; // マゼンタ度: R/B が高く G が低いほど大
    if (m >= HI) {
      data[i + 3] = 0;
    } else if (m > LO) {
      const t = (m - LO) / (HI - LO);
      data[i + 3] = Math.round(data[i + 3] * (1 - t));
      // 縁のマゼンタかぶりを軽減
      const spill = m - LO;
      data[i] = Math.max(0, r - spill);
      data[i + 2] = Math.max(0, b - spill);
    }
  }
  return sharp(data, { raw: { width: info.width, height: info.height, channels: 4 } })
    .png()
    .toBuffer();
}

/** 生成画像をアセット仕様に整えて一時ファイルへ書き、完成後に本来の場所へ移動 */
async function processAndSave(asset, img) {
  let buf = Buffer.from(img.data, 'base64');

  if (asset.transparent && !(await hasRealAlpha(buf))) {
    buf = await chromaKey(buf);
  }

  const [w, h] = asset.size;
  let pipeline = sharp(buf);
  if (asset.format === 'webp') {
    pipeline = pipeline.resize(w, h, { fit: 'cover' }).webp({ quality: 72 });
  } else {
    pipeline = pipeline
      .resize(w, h, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } })
      .png({ palette: true, quality: 80, compressionLevel: 9 });
  }
  const out = await pipeline.toBuffer();

  const finalPath = path.join(PUBLIC, asset.out);
  const tmpPath = path.join(TMP_DIR, asset.out.replaceAll('/', '__'));
  await mkdir(path.dirname(finalPath), { recursive: true });
  await writeFile(tmpPath, out);
  await rename(tmpPath, finalPath);

  const kb = (out.length / 1024).toFixed(0);
  console.log(`✓ ${asset.out} (${kb}KB)`);
  if (out.length > 200 * 1024) {
    console.warn(`  ⚠ 200KB を超えています(${kb}KB)。圧縮設定の見直しを検討してください`);
  }
}

async function exists(p) {
  try {
    await stat(p);
    return true;
  } catch {
    return false;
  }
}

async function shouldSkip(asset) {
  if (force) return false;
  return exists(path.join(PUBLIC, asset.out));
}

// ---------------------------------------------------------------------------
// 実行
// ---------------------------------------------------------------------------

/** fairy は参照画像方式(1枚目=基準、残りは基準を参照して同一キャラクター化) */
async function runFairy(ai) {
  const fairies = ASSETS.filter((a) => a.group === 'fairy');
  const pending = [];
  for (const a of fairies) {
    if (await shouldSkip(a)) console.log(`- ${a.out} は生成済み(スキップ。--force で再生成)`);
    else pending.push(a);
  }
  if (pending.length === 0) return;

  // 基準画像は常に normal。normal 自体がスキップ対象でも、他の表情を
  // 作るためには基準が必要なので、その場合は normal を生成し直さず
  // 生成済みファイルを参照画像として読む…のではなく、キャラクター一貫性を
  // 最優先し、pending がある限り normal から作り直す(既存 normal は上書き)。
  console.log('基準画像を生成中 (fairy-normal)...');
  const base = ASSETS.find((a) => a.id === 'fairy-normal');
  const baseImage = await generate(
    ai,
    `${STYLE}\n${CHARACTER}\n表情とポーズ: ${base.prompt}\n${CHROMA_BG}`,
    base.aspect,
  );
  await processAndSave(base, baseImage);

  for (const a of fairies.filter((x) => x.id !== 'fairy-normal')) {
    if (!pending.includes(a)) continue;
    console.log(`参照画像方式で生成中 (${a.id})...`);
    const img = await generate(ai, `表情とポーズ: ${a.prompt}\n${CHROMA_BG}`, a.aspect, baseImage);
    await processAndSave(a, img);
    await sleep(1500);
  }
}

async function runSimple(ai, asset) {
  if (await shouldSkip(asset)) {
    console.log(`- ${asset.out} は生成済み(スキップ。--force で再生成)`);
    return;
  }
  console.log(`生成中 (${asset.id})...`);
  const prompt = `${STYLE}\n${asset.prompt}${asset.transparent ? `\n${CHROMA_BG}` : ''}`;
  const img = await generate(ai, prompt, asset.aspect);
  await processAndSave(asset, img);
  await sleep(1500);
}

const ai = makeClient();
await mkdir(TMP_DIR, { recursive: true });

const failures = [];

if (inScope({ group: 'fairy' })) {
  try {
    await runFairy(ai);
  } catch (err) {
    console.error(`✗ fairy: ${err.message ?? err}`);
    failures.push('fairy');
  }
}
for (const asset of ASSETS.filter((a) => a.group !== 'fairy' && inScope(a))) {
  try {
    await runSimple(ai, asset);
  } catch (err) {
    console.error(`✗ ${asset.id}: ${err.message ?? err}`);
    failures.push(asset.id);
  }
}

console.log('');
console.log(`API 呼び出し(画像生成)回数: ${generatedCount} 枚`);
if (failures.length) {
  console.error(`失敗: ${failures.join(', ')}`);
  console.error('失敗分のみ再実行するには、そのまま同じコマンドを再実行してください(生成済みはスキップされます)。');
  process.exit(1);
}
console.log('完了。public/fairy/ と public/art/ を確認してください。');
