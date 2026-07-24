import type { VercelRequest, VercelResponse } from '@vercel/node';
import { GoogleGenAI, Type } from '@google/genai';

/**
 * しゃべる絵本メーカー: 絵本自動生成のサーバーレス関数。
 *
 * 子どもが選んだ5つのアイコンキーワードから、
 *   1) 物語(日本語・短文JSON)
 *   2) 各ページの挿絵(Nano Banana系画像モデル)
 *   3) 各ページのナレーション音声(Gemini TTS, PCM→WAV)
 * を生成してクライアントに返す。GEMINI_API_KEYはサーバー側だけで保持し、
 * クライアントには絶対に露出しない。
 *
 * 生成の入出力契約は src/lib/generateApi.ts と一致させること(型はここに自己完結で定義)。
 */

// --- モデルは環境変数で差し替え可能(Nano Banana系は改廃が速いため) ---
const TEXT_MODEL = process.env.GEMINI_TEXT_MODEL || 'gemini-2.5-flash';
const IMAGE_MODEL = process.env.GEMINI_IMAGE_MODEL || 'gemini-2.5-flash-image';
const TTS_MODEL = process.env.GEMINI_TTS_MODEL || 'gemini-2.5-flash-preview-tts';
// 優しい女性声(日本語対応のプリセット声)
const TTS_VOICE = process.env.GEMINI_TTS_VOICE || 'Leda';

// ページ数は生成時間・コストを抑えるため固定(Vercel Hobbyの60秒制限対策)
const PAGE_COUNT = 6;

// 全ページで画風を揃えるためのスタイル指定(挿絵プロンプトに必ず付加)
const STYLE_SUFFIX =
  ', 温かみのあるやわらかい色合いの手描き絵本イラスト、丸みのある優しいタッチ、' +
  'パステルカラー、明るく安全で楽しい雰囲気、文字やテキストは一切入れない、白い余白のある構図';

// Vercelサーバーレス関数の最大実行時間(秒)
export const config = { maxDuration: 60 };

interface StoryPage {
  text: string;
  imagePrompt: string;
}
interface Story {
  title: string;
  pages: StoryPage[];
}

/** 16bit PCM(base64)をWAV(base64)に包む。iOS SafariのAudioで再生可能にする。 */
function pcmToWavBase64(pcmBase64: string, sampleRate: number): string {
  const pcm = Buffer.from(pcmBase64, 'base64');
  const numChannels = 1;
  const bitsPerSample = 16;
  const byteRate = (sampleRate * numChannels * bitsPerSample) / 8;
  const blockAlign = (numChannels * bitsPerSample) / 8;
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + pcm.length, 4);
  header.write('WAVE', 8);
  header.write('fmt ', 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(numChannels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write('data', 36);
  header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]).toString('base64');
}

/** mimeType 文字列(例 'audio/L16;codec=pcm;rate=24000')からサンプルレートを抽出 */
function sampleRateFromMime(mime: string | undefined): number {
  const m = mime?.match(/rate=(\d+)/);
  return m ? parseInt(m[1], 10) : 24000;
}

/** レスポンスのpartsから最初のinlineData(base64バイナリ)を取り出す */
function firstInlineData(
  resp: { candidates?: Array<{ content?: { parts?: Array<{ inlineData?: { data?: string; mimeType?: string } }> } }> },
): { data: string; mimeType: string } | null {
  const parts = resp.candidates?.[0]?.content?.parts ?? [];
  for (const p of parts) {
    if (p.inlineData?.data) {
      return { data: p.inlineData.data, mimeType: p.inlineData.mimeType ?? '' };
    }
  }
  return null;
}

/** 物語生成: 5キーワードから、子ども向けの短い日本語のお話をJSONで得る */
async function generateStory(ai: GoogleGenAI, icons: string[]): Promise<Story> {
  const prompt =
    `つぎの5つのことばを ぜんぶ つかって、ちいさなこどものための やさしい えほんの おはなしを つくってください。\n` +
    `ことば: ${icons.join('、')}\n\n` +
    `じょうけん:\n` +
    `- たいしょうは 2さいと 5さいの こども。かていで よむ えほんです。\n` +
    `- ぜんぶで ${PAGE_COUNT}ページ。\n` +
    `- 1ページの ぶんは 1〜2ぶんの みじかい ひらがな中心の やさしい にほんご。\n` +
    `- あんぜんで あたたかい ないよう。こわい・あぶない・ぼうりょくてきな ひょうげんは いれない。\n` +
    `- 5つの ことばが しぜんに とうじょうする、たのしい ストーリーにする。\n` +
    `- 各ページの imagePrompt は、そのページの ばめんを えがくための にほんご せつめい` +
    `(とうじょうする もの・ばしょ・うごきを ぐたいてきに)。とうじょうキャラクターの みためが` +
    `ぜんページで いっかんするように、いろや とくちょうを かく。`;

  const resp = await ai.models.generateContent({
    model: TEXT_MODEL,
    contents: prompt,
    config: {
      responseMimeType: 'application/json',
      responseSchema: {
        type: Type.OBJECT,
        properties: {
          title: { type: Type.STRING },
          pages: {
            type: Type.ARRAY,
            items: {
              type: Type.OBJECT,
              properties: {
                text: { type: Type.STRING },
                imagePrompt: { type: Type.STRING },
              },
              required: ['text', 'imagePrompt'],
            },
          },
        },
        required: ['title', 'pages'],
      },
      temperature: 0.9,
    },
  });

  const story = JSON.parse(resp.text ?? '{}') as Story;
  if (!story.title || !Array.isArray(story.pages) || story.pages.length === 0) {
    throw new Error('story generation returned invalid structure');
  }
  // 念のためページ数を上限で切る
  story.pages = story.pages.slice(0, PAGE_COUNT);
  return story;
}

/** 挿絵生成: imagePromptから1枚の画像(base64)を得る */
async function generateImage(
  ai: GoogleGenAI,
  imagePrompt: string,
): Promise<{ data: string; mimeType: string }> {
  const resp = await ai.models.generateContent({
    model: IMAGE_MODEL,
    contents: imagePrompt + STYLE_SUFFIX,
    config: { responseModalities: ['IMAGE'] },
  });
  const img = firstInlineData(resp);
  if (!img) throw new Error('image generation returned no image');
  return { data: img.data, mimeType: img.mimeType || 'image/png' };
}

/** 音声生成: textを日本語の優しい声で読み上げ、WAV(base64)で得る。失敗時はnull。 */
async function generateAudio(
  ai: GoogleGenAI,
  text: string,
): Promise<{ data: string; mimeType: string } | null> {
  try {
    const resp = await ai.models.generateContent({
      model: TTS_MODEL,
      contents: text,
      config: {
        responseModalities: ['AUDIO'],
        speechConfig: {
          voiceConfig: { prebuiltVoiceConfig: { voiceName: TTS_VOICE } },
        },
      },
    });
    const audio = firstInlineData(resp);
    if (!audio) return null;
    const rate = sampleRateFromMime(audio.mimeType);
    return { data: pcmToWavBase64(audio.data, rate), mimeType: 'audio/wav' };
  } catch {
    // 音声はフォールバック(クライアントのWeb Speech TTS)があるので、失敗しても致命的ではない
    return null;
  }
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'method not allowed' });
    return;
  }

  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    res.status(500).json({ error: 'GEMINI_API_KEY is not configured' });
    return;
  }

  // --- 入力検証(APIキー濫用を防ぐため、5つの短い文字列に限定) ---
  const icons = (req.body as { icons?: unknown })?.icons;
  if (
    !Array.isArray(icons) ||
    icons.length !== 5 ||
    !icons.every((s) => typeof s === 'string' && s.length > 0 && s.length <= 20)
  ) {
    res.status(400).json({ error: 'icons must be an array of 5 short strings' });
    return;
  }

  try {
    const ai = new GoogleGenAI({ apiKey });

    // 1) 物語生成
    const story = await generateStory(ai, icons as string[]);

    // 2)3) 各ページの挿絵・音声を並列生成(60秒制限対策)
    const pages = await Promise.all(
      story.pages.map(async (page) => {
        const [image, audio] = await Promise.all([
          generateImage(ai, page.imagePrompt),
          generateAudio(ai, page.text),
        ]);
        return {
          text: page.text,
          imageBase64: image.data,
          imageMime: image.mimeType,
          audioBase64: audio?.data ?? null,
          audioMime: audio?.mimeType ?? null,
        };
      }),
    );

    res.status(200).json({ title: story.title, pages });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'unknown error';
    res.status(502).json({ error: `generation failed: ${message}` });
  }
}
