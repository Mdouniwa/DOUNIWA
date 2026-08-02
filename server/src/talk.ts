/**
 * 対話ロジック: えほんの精が子どもと会話しながら物語の材料を集める。
 *
 * - 質問はテンプレートではなく、前の答えを受けてAIが毎回生成する
 * - 音声回答は文字起こしを挟まず、Geminiに直接聞かせて意図を解釈する
 * - 脱線した答えも否定せず物語の要素として拾う
 * - 聞き取れない場合は聞き返し、3回失敗で選択肢へ自然に誘導する
 */
import { Type } from '@google/genai';
import { getAI } from './genai.js';
import { config } from './env.js';
import { synthesizeSpeech } from './tts.js';
import type {
  FairyExpression,
  TalkChoice,
  TalkNextRequest,
  TalkNextResponse,
  TalkTurn,
} from './contract.js';

/** 集める材料の数(=質問数の目安)。骨格: 主役→場所→していること→だれと→さいご */
export const QUESTION_TARGET = 5;

const EXPRESSIONS: FairyExpression[] = ['normal', 'happy', 'thinking', 'surprised', 'cheer'];

const SYSTEM_PROMPT = `あなたは「えほんの精」。てのひらに のるくらいの ちいさな 妖精の女の子です。
2さいから5さいの こどもと おしゃべりしながら、いっしょに えほんの おはなしを つくります。

# やくわり
こどもに 1つずつ しつもんして、おはなしの ざいりょうを あつめる。
ながれの ほねぐみ(この じゅんばんを めやすにする):
1. しゅやくを きめる(だれ・なにが でてくる?)
2. ばしょを きめる(どこに いる?)
3. そこで なにを しているか
4. だれと いっしょか(こども じしんが とうじょうする みちすじを つくる)
5. さいごは どうなるか(たのしい おち)

# きまり
- せりふは ひらがな中心の みじかい やさしい にほんご。1〜2ぶん。ことばの あいだに はんかくスペースを いれて よみやすくする。
- まえの こたえを かならず うれしそうに うけとめてから(あいづち)、つぎの しつもんを する。あいづちは こたえの ないように ふれること。
- おなじ いいまわしを くりかえさない。かいわとして しぜんに つなげる。
- こどもの こたえが しつもんと ずれていても ぜったいに ひていしない。その ないようを おはなしの ざいりょうとして ひろって すすめる。
- 「わからない」「うーん」のような こたえや むごんの ときは、たのしい れいを 2〜3こ あげて たすける。
- choices は いまの しつもんに タップで こたえられる せんたくし4つ。えもじ1つ + みじかい ことば(ひらがな、6もじいない)。こどもが よろこびそうな バラエティに すること。
- えもじは かならず カラーひょうじの かんぜんな かたちで 出力すること(異体字セレクタ U+FE0F が ひつような えもじには かならず つける。例: 🏞️ ✈️ ☀️)。
- expression は 精の ひょうじょう: happy(うれしい)/ thinking(かんがえる)/ surprised(びっくり)/ cheer(かんせいを よろこぶ)/ normal。こたえに すなおに はんのうして えらぶ。
- ざいりょうが ${QUESTION_TARGET}こ そろったら done=true。しめの せりふは「すてきな おはなしが できたよ! えほんに するね!」のように よろこぶ(expression=cheer)。done=true のとき choices は から配列で よい。

# 音声のこたえについて
こどもの こえの 録音が そえられている ばあい、まず その ないようを きいて、こどもが いった ことを answerText に にほんごで かく(いいまちがいは やさしく くみとる)。
きこえない・むごん・ざつおんだけの ばあいは answerText を null、retry を true にして、question は「ごめんね、もういっかい いってくれる?」のような やさしい ききかえしに する。
テキストの こたえの ばあいは answerText に そのまま いれて、retry は false。

かならず しじされた JSON だけを かえすこと。`;

const RESPONSE_SCHEMA = {
  type: Type.OBJECT,
  properties: {
    answerText: {
      type: Type.STRING,
      nullable: true,
      description: '解釈した子どもの答え。聞き取れなければnull',
    },
    retry: { type: Type.BOOLEAN, description: '聞き取れず聞き返す場合true' },
    question: { type: Type.STRING, description: '精のせりふ(相槌+次の質問、または聞き返し)' },
    choices: {
      type: Type.ARRAY,
      items: {
        type: Type.OBJECT,
        properties: {
          emoji: { type: Type.STRING },
          label: { type: Type.STRING },
        },
        required: ['emoji', 'label'],
      },
    },
    expression: { type: Type.STRING, enum: EXPRESSIONS },
    done: { type: Type.BOOLEAN },
  },
  required: ['retry', 'question', 'choices', 'expression', 'done'],
} as const;

interface ModelReply {
  answerText?: string | null;
  retry: boolean;
  question: string;
  choices: TalkChoice[];
  expression: FairyExpression;
  done: boolean;
}

/** 会話履歴を人が読めるテキストに直す(モデルへの入力用) */
function historyText(history: TalkTurn[]): string {
  if (history.length === 0) return '(まだ会話は始まっていない)';
  return history.map((t) => `精: ${t.question}\n子ども: ${t.answer}`).join('\n');
}

/**
 * 絵文字を正規化する。モデルが異体字セレクタ(VS16, U+FE0F)を欠いた
 * 絵文字(例: "🏞" "✈")を返すと、iOSで白黒の記号や豆腐になるため、
 * 単一コードポイントでVS16が無いものには補う。ZWJ絵文字・肌色つき等の
 * 複合シーケンスはそのまま通す(VS16は不要な絵文字に付いても無視される)。
 */
const VS16 = '\uFE0F';

function normalizeEmoji(raw: string): string {
  const emoji = raw.trim();
  if (!emoji) return `⭐${VS16}`; // ⭐️
  const codePoints = [...emoji];
  if (codePoints.length === 1 && !emoji.includes(VS16)) {
    return emoji + VS16;
  }
  return emoji;
}

/** モデル出力の choices を安全な形に整える(欠け・過剰・空文字・VS16欠け対策) */
function sanitizeChoices(choices: unknown): TalkChoice[] {
  if (!Array.isArray(choices)) return [];
  return choices
    .filter(
      (c): c is TalkChoice =>
        typeof c === 'object' &&
        c !== null &&
        typeof (c as TalkChoice).emoji === 'string' &&
        typeof (c as TalkChoice).label === 'string' &&
        (c as TalkChoice).label.length > 0,
    )
    .slice(0, 4)
    .map((c) => ({ emoji: normalizeEmoji(c.emoji), label: c.label }));
}

export async function talkNext(req: TalkNextRequest): Promise<TalkNextResponse> {
  const history = req.history;
  const failCount = req.failCount ?? 0;

  // --- モデルへの指示を組み立てる ---
  const lines: string[] = [`これまでの会話:\n${historyText(history)}`];

  const parts: Array<
    { text: string } | { inlineData: { data: string; mimeType: string } }
  > = [];

  if (!req.answer) {
    lines.push(
      history.length === 0
        ? 'いま会話が始まったところ。こどもへの あいさつと さいしょの しつもんをして。'
        : 'まだ答えは来ていない。同じ材料についての質問を、言い方を変えてもう一度して。',
    );
  } else if (req.answer.text !== undefined) {
    lines.push(`こどもがタップで答えた: 「${req.answer.text}」`);
  } else if (req.answer.audioBase64) {
    lines.push('こどもの声の録音を添付する。内容を解釈して答えとして扱って。');
  }

  if (failCount >= 2) {
    lines.push(
      `聞き取りの失敗が${failCount}回続いている。責めずに、choicesから選べばいいことをやさしく伝えて。`,
    );
  }
  lines.push(`集める材料はぜんぶで${QUESTION_TARGET}こ。いま${history.length}こ集まっている。`);

  parts.push({ text: lines.join('\n\n') });
  if (req.answer?.audioBase64) {
    parts.push({
      inlineData: {
        data: req.answer.audioBase64,
        mimeType: req.answer.audioMime || 'audio/mp4',
      },
    });
  }

  // --- 質問生成(音声理解も同じ呼び出しで行う) ---
  const resp = await getAI().models.generateContent({
    model: config.chatModel,
    contents: [{ role: 'user', parts }],
    config: {
      systemInstruction: SYSTEM_PROMPT,
      responseMimeType: 'application/json',
      responseSchema: RESPONSE_SCHEMA,
      temperature: 0.9,
    },
  });

  const reply = JSON.parse(resp.text ?? '{}') as ModelReply;
  if (!reply.question) {
    throw new Error('talk model returned invalid structure');
  }

  const retry = Boolean(reply.retry);
  const answered = Boolean(req.answer) && !retry;
  const answeredCount = history.length + (answered ? 1 : 0);
  // 安全弁: モデルがdoneを出し損ねても質問しすぎない
  const done = Boolean(reply.done) || answeredCount >= QUESTION_TARGET + 1;

  const choices = sanitizeChoices(reply.choices);
  const expression = EXPRESSIONS.includes(reply.expression) ? reply.expression : 'normal';

  // --- 質問の読み上げ音声(失敗時はnull → クライアントでWeb Speechへ) ---
  const tts = await synthesizeSpeech(reply.question);

  return {
    answerText: reply.answerText ?? (req.answer?.text ?? null),
    retry,
    question: reply.question,
    questionAudioBase64: tts?.base64 ?? null,
    questionAudioMime: tts?.mime ?? null,
    choices,
    expression: done ? 'cheer' : expression,
    remaining: Math.max(0, QUESTION_TARGET - answeredCount),
    done,
  };
}
