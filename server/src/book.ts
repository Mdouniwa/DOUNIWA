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

interface StoryCharacter {
  /** よびな(例: 男の子、パパ、ママ)。imagePromptからの参照に使う */
  name: string;
  /** 見た目の詳細(髪型・髪の色・服装・ひげの有無・体格など) */
  appearance: string;
}

interface Story {
  title: string;
  characters: StoryCharacter[];
  pages: Array<{ text: string; imagePrompt: string }>;
}

/** キャラクターシートに載せる最大人数(Nano Banana 2の一貫性保持は5人まで) */
const MAX_CHARACTERS = 5;

interface Job {
  response: BookJobResponse;
  createdAt: number;
}

const jobs = new Map<string, Job>();

/**
 * 一時的なAPI障害(503高負荷・429レート制限など)に備えたリトライ。
 * 挿絵1枚の失敗で絵本全体が失敗しないようにする。
 */
async function withRetry<T>(label: string, fn: () => Promise<T>): Promise<T> {
  const waits = [5000, 15000];
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn();
    } catch (err) {
      if (attempt >= waits.length) throw err;
      const message = err instanceof Error ? err.message : String(err);
      console.warn(`[book] ${label} 失敗、${waits[attempt] / 1000}s後にリトライ: ${message}`);
      await new Promise((r) => setTimeout(r, waits[attempt]));
    }
  }
}

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
- characters: 挿絵に登場する人物・キャラクター(最大${MAX_CHARACTERS}人、主人公を最初に)。
  name はよびな(例: 男の子、パパ、ママ、うさぎさん)。
  appearance は見た目の詳細(髪型・髪の色・服装と色・ひげの有無・体格・大きさを具体的に)。
  挿絵のキャラクターシートを作るために使うので、全ページで変わらない特徴を書くこと。
- 各ページの imagePrompt: そのページの場面の日本語説明(登場するもの・場所・動きを具体的に)。登場人物は characters の name で呼ぶこと(見た目はキャラクターシートで揃えるため繰り返さない)。`;

  const resp = await getAI().models.generateContent({
    model: config.storyModel,
    contents: prompt,
    config: {
      responseMimeType: 'application/json',
      responseSchema: {
        type: Type.OBJECT,
        properties: {
          title: { type: Type.STRING },
          characters: {
            type: Type.ARRAY,
            items: {
              type: Type.OBJECT,
              properties: {
                name: { type: Type.STRING },
                appearance: { type: Type.STRING },
              },
              required: ['name', 'appearance'],
            },
          },
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
        required: ['title', 'characters', 'pages'],
      },
      temperature: 0.9,
    },
  });

  const story = JSON.parse(resp.text ?? '{}') as Story;
  if (
    !story.title ||
    !Array.isArray(story.characters) ||
    story.characters.length === 0 ||
    !Array.isArray(story.pages) ||
    story.pages.length === 0
  ) {
    throw new Error('story generation returned invalid structure');
  }
  story.characters = story.characters.slice(0, MAX_CHARACTERS);
  story.pages = story.pages.slice(0, PAGE_COUNT);
  return story;
}

/** 登場人物の一覧をプロンプト用テキストに直す */
function charactersText(characters: StoryCharacter[]): string {
  return characters.map((c, i) => `${i + 1}. ${c.name}: ${c.appearance}`).join('\n');
}

/**
 * 登場人物「全員」を1枚に描いたキャラクターシートを生成する(参照画像方式の基準)。
 * 主人公だけを固定すると2人目以降(パパ・ママ等)がページごとに別人になるため、
 * 最大${MAX_CHARACTERS}人を1枚に並べて全員の見た目を固定する。
 */
async function generateCharacterSheet(
  characters: StoryCharacter[],
): Promise<{ data: string; mimeType: string }> {
  const resp = await getAI().models.generateContent({
    model: config.imageModel,
    contents:
      `絵本の登場人物ぜんぶを1枚に描いたキャラクターシート。\n` +
      `登場人物(左からこの順番に並べる):\n${charactersText(characters)}\n` +
      `全員の全身の立ち姿を正面から、それぞれはっきり大きく描く。おたがいに重ならないこと。\n` +
      `背景はシンプルな1色。文字・名前・ラベルは入れない。${STYLE_SUFFIX}`,
    config: {
      responseModalities: ['IMAGE'],
      imageConfig: { aspectRatio: characters.length >= 3 ? '16:9' : '4:3' },
    },
  });
  const img = firstInlineData(resp);
  if (!img) throw new Error('character sheet generation returned no image');
  return { data: img.data, mimeType: img.mimeType || 'image/png' };
}

/**
 * ページ挿絵を生成する。キャラクターシートを参照画像として渡し、
 * 登場人物「全員」の見た目を固定する。参照画像だけでは場面が複雑なときに
 * 追従が落ちるため、各人物の特徴テキストも併用して二重に固定する。
 */
async function generatePageImage(
  imagePrompt: string,
  characters: StoryCharacter[],
  characterSheet: { data: string; mimeType: string },
): Promise<{ data: string; mimeType: string }> {
  const names = characters.map((c) => c.name).join('、');
  const resp = await getAI().models.generateContent({
    model: config.imageModel,
    contents: [
      {
        role: 'user',
        parts: [
          { inlineData: { data: characterSheet.data, mimeType: characterSheet.mimeType } },
          {
            text:
              `添付した参照画像は、この絵本の登場人物ぜんぶ(左から: ${names})のキャラクターシートです。\n` +
              `【最重要】場面に登場する人物は全員、参照画像の同一人物として描くこと。` +
              `それぞれの髪型・髪の色・肌の色・目・服装・色づかい・ひげの有無・体型・画風を参照画像と厳密に一致させること。` +
              `参照画像とちがう見た目(別の髪型・別の色の髪・別の服・ひげの有無の変化)にしてはならない。\n` +
              `登場人物の見た目(参照画像と同じ):\n${charactersText(characters)}\n` +
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

    // 2) 登場人物全員のキャラクターシート(参照画像方式の基準)
    const characterRef = await withRetry('character sheet', () =>
      generateCharacterSheet(story.characters),
    );
    update(jobId, { status: 'pages', progress: 0.3 });

    // 3) 各ページの挿絵(参照画像方式)。レート制限を避けるため順次生成
    const images: Array<{ data: string; mimeType: string }> = [];
    for (let i = 0; i < story.pages.length; i++) {
      images.push(
        await withRetry(`page ${i + 1}`, () =>
          generatePageImage(story.pages[i].imagePrompt, story.characters, characterRef),
        ),
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
