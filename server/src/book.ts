/**
 * 絵本生成パイプライン: 対話ログ → 物語 → 挿絵(参照画像方式) → 音声合成。
 *
 * v4からの最重要改善 = 挿絵の一貫性:
 *   1. まず主人公の「基準画像」を1枚生成する
 *   2. 以降の全ページは基準画像を参照画像としてリクエストに渡す
 *   3. 全ページで同じキャラクターが登場する絵本にする
 *
 * 生成には30秒〜1分かかるため、ジョブ方式(開始→ポーリング)で返す。
 * iOSのfetchが長時間リクエストで切られる問題も同時に回避する。
 */
import { randomUUID } from 'node:crypto';
import { Type } from '@google/genai';
import { getAI, firstInlineData } from './genai.js';
import { config } from './env.js';
import { synthesizeSpeech } from './tts.js';
import type { BookJobResponse, BookPageResult, TalkTurn } from './contract.js';

const PAGE_COUNT = 6;

/** 全ページで画風を揃えるためのスタイル指定(全ての挿絵プロンプトに付加) */
const STYLE_SUFFIX =
  '\n画風: 温かみのあるやわらかい色合いの手描き絵本イラスト、丸みのある優しいタッチ、' +
  'パステルカラー、明るく安全で楽しい雰囲気。文字やテキストは一切入れない。';

interface Story {
  title: string;
  characterDescription: string;
  pages: Array<{ text: string; imagePrompt: string }>;
}

interface Job {
  response: BookJobResponse;
  createdAt: number;
}

const jobs = new Map<string, Job>();

/** 30分より古いジョブは捨てる(メモリリーク防止) */
function gcJobs(): void {
  const cutoff = Date.now() - 30 * 60 * 1000;
  for (const [id, job] of jobs) {
    if (job.createdAt < cutoff) jobs.delete(id);
  }
}

export function getJob(jobId: string): BookJobResponse | null {
  gcJobs();
  return jobs.get(jobId)?.response ?? null;
}

/** 物語生成: 対話ログから、起承転結のある子ども向けの短いお話をJSONで得る */
async function generateStory(conversation: TalkTurn[]): Promise<Story> {
  const log = conversation.map((t) => `精: ${t.question}\n子ども: ${t.answer}`).join('\n');
  const prompt = `「えほんの精」と子どもの会話から、ちいさな子どものための やさしい絵本のお話を作ってください。

会話:
${log}

条件:
- 対象は2歳と5歳の子ども。家庭で読む絵本です。
- 全部で${PAGE_COUNT}ページ。起承転結があり、会話で子どもが答えた要素をぜんぶ大切に使うこと。
- 1ページの文は1〜2文の短い、ひらがな中心のやさしい日本語。
- 安全で温かい内容。こわい・あぶない・暴力的な表現は入れない。
- 会話に子ども自身が登場していたら、お話にも登場させること。
- characterDescription: 主人公の見た目の詳細な説明(髪型・髪の色・服装・色・特徴・大きさを具体的に)。挿絵の基準画像を作るために使う。
- 各ページの imagePrompt: そのページの場面の日本語説明(登場するもの・場所・動きを具体的に)。主人公は「主人公」と書くだけでよい(見た目は基準画像とcharacterDescriptionで揃える)。`;

  const resp = await getAI().models.generateContent({
    model: config.storyModel,
    contents: prompt,
    config: {
      responseMimeType: 'application/json',
      responseSchema: {
        type: Type.OBJECT,
        properties: {
          title: { type: Type.STRING },
          characterDescription: { type: Type.STRING },
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
        required: ['title', 'characterDescription', 'pages'],
      },
      temperature: 0.9,
    },
  });

  const story = JSON.parse(resp.text ?? '{}') as Story;
  if (!story.title || !story.characterDescription || !Array.isArray(story.pages) || story.pages.length === 0) {
    throw new Error('story generation returned invalid structure');
  }
  story.pages = story.pages.slice(0, PAGE_COUNT);
  return story;
}

/** 主人公の基準画像を生成する(参照画像方式の1枚目) */
async function generateCharacterRef(
  characterDescription: string,
): Promise<{ data: string; mimeType: string }> {
  const resp = await getAI().models.generateContent({
    model: config.imageModel,
    contents:
      `絵本の主人公のキャラクターシート。同一キャラクターの全身の立ち姿を正面から、はっきり大きく描く。\n` +
      `主人公: ${characterDescription}\n背景はシンプルな1色。${STYLE_SUFFIX}`,
    config: {
      responseModalities: ['IMAGE'],
      imageConfig: { aspectRatio: '3:4' },
    },
  });
  const img = firstInlineData(resp);
  if (!img) throw new Error('character reference image generation returned no image');
  return { data: img.data, mimeType: img.mimeType || 'image/png' };
}

/**
 * ページ挿絵を生成する。基準画像を参照画像として渡し、キャラクターの見た目を固定する。
 * 参照画像だけでは場面が複雑なとき(他の登場人物・背景が多いとき)に追従が
 * 落ちるため、characterDescription のテキストも併用して二重に固定する。
 */
async function generatePageImage(
  imagePrompt: string,
  characterDescription: string,
  characterRef: { data: string; mimeType: string },
): Promise<{ data: string; mimeType: string }> {
  const resp = await getAI().models.generateContent({
    model: config.imageModel,
    contents: [
      {
        role: 'user',
        parts: [
          { inlineData: { data: characterRef.data, mimeType: characterRef.mimeType } },
          {
            text:
              `添付した参照画像は、この絵本の主人公のキャラクターシートです。\n` +
              `【最重要】場面の中の主人公は、参照画像とまったく同一のキャラクターとして描くこと。` +
              `髪型・髪の色・肌の色・目・服装・色づかい・体型・画風を参照画像と厳密に一致させること。` +
              `参照画像とちがう見た目(別の髪型・別の色の髪・別の服)にしてはならない。\n` +
              `主人公の見た目(参照画像と同じ): ${characterDescription}\n` +
              `場面: ${imagePrompt}${STYLE_SUFFIX}`,
          },
        ],
      },
    ],
    config: {
      responseModalities: ['IMAGE'],
      imageConfig: { aspectRatio: '4:3' },
    },
  });
  const img = firstInlineData(resp);
  if (!img) throw new Error('page image generation returned no image');
  return { data: img.data, mimeType: img.mimeType || 'image/png' };
}

function update(jobId: string, patch: Partial<BookJobResponse>): void {
  const job = jobs.get(jobId);
  if (job) job.response = { ...job.response, ...patch };
}

/** パイプライン本体(非同期実行、進捗はジョブに書き込む) */
async function runPipeline(jobId: string, conversation: TalkTurn[]): Promise<void> {
  try {
    // 1) 物語
    const story = await generateStory(conversation);
    update(jobId, { status: 'character', progress: 0.2 });

    // 2) 主人公の基準画像
    const characterRef = await generateCharacterRef(story.characterDescription);
    update(jobId, { status: 'pages', progress: 0.3 });

    // 3) 各ページの挿絵(参照画像方式)。レート制限を避けるため順次生成
    const images: Array<{ data: string; mimeType: string }> = [];
    for (let i = 0; i < story.pages.length; i++) {
      images.push(
        await generatePageImage(story.pages[i].imagePrompt, story.characterDescription, characterRef),
      );
      update(jobId, { progress: 0.3 + 0.5 * ((i + 1) / story.pages.length) });
    }
    update(jobId, { status: 'audio', progress: 0.8 });

    // 4) ナレーション音声(失敗ページはnull → クライアントでWeb Speechフォールバック)
    const audios = await Promise.all(story.pages.map((p) => synthesizeSpeech(p.text)));

    const pages: BookPageResult[] = story.pages.map((p, i) => ({
      text: p.text,
      imageBase64: images[i].data,
      imageMime: images[i].mimeType,
      audioBase64: audios[i]?.base64 ?? null,
      audioMime: audios[i]?.mime ?? null,
    }));

    update(jobId, {
      status: 'done',
      progress: 1,
      result: {
        title: story.title,
        characterRefBase64: characterRef.data,
        characterRefMime: characterRef.mimeType,
        pages,
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'unknown error';
    console.error('[book]', message);
    update(jobId, { status: 'error', progress: 1, error: message });
  }
}

/** 生成ジョブを開始し、jobIdを返す */
export function startBookJob(conversation: TalkTurn[]): string {
  gcJobs();
  const jobId = randomUUID();
  jobs.set(jobId, {
    createdAt: Date.now(),
    response: { status: 'story', progress: 0.05 },
  });
  void runPipeline(jobId, conversation);
  return jobId;
}
