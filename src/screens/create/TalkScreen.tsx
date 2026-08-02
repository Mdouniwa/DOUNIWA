import { useCallback, useEffect, useRef, useState } from 'react';
import {
  talkNext,
  base64ToBlob,
  blobToBase64,
  QUESTION_TARGET,
  FIRST_QUESTION,
  FIRST_QUESTION_AUDIO,
  type FairyExpression,
  type TalkNextRequest,
  type TalkNextResponse,
  type TalkTurn,
} from '../../lib/talkApi';
import { speak, cancelSpeech } from '../../lib/tts';
import { playAudioBlob, stopAudioPlayback } from '../../lib/audioPlayback';
import { playSound } from '../../lib/soundEffects';
import { useRecorder } from '../../hooks/useRecorder';
import { ART, FAIRY_IMAGES } from '../../lib/artAssets';
import { ArtBg } from '../../components/ArtBg';
import './talk.css';

interface TalkScreenProps {
  /** 対話が完了したとき、集めた対話ログを渡す */
  onDone: (conversation: TalkTurn[]) => void;
  /** やめる(ホームへ) */
  onQuit: () => void;
}

/**
 * 1問目は固定(サーバーを呼ばず待ち時間ゼロで対話を始める)。
 * 音声は事前生成した静的ファイル(public/audio/)を使う。
 */
const FIRST_RESPONSE: TalkNextResponse = {
  answerText: null,
  retry: false,
  question: FIRST_QUESTION,
  questionAudioBase64: null,
  questionAudioMime: null,
  choices: [
    { emoji: '🐻', label: 'どうぶつ' },
    { emoji: '🚂', label: 'のりもの' },
    { emoji: '👨‍👩‍👧', label: 'かぞく' },
    { emoji: '🧒', label: 'おともだち' },
  ],
  expression: 'happy',
  remaining: QUESTION_TARGET,
  done: false,
};

/** 1問目の固定音声を再生(取得や再生に失敗したらWeb Speechへ) */
async function playFirstQuestion(): Promise<void> {
  try {
    const res = await fetch(FIRST_QUESTION_AUDIO);
    if (!res.ok) throw new Error(`audio fetch failed (${res.status})`);
    await playAudioBlob(await res.blob());
  } catch (err) {
    console.error('[talk] 固定1問目の音声再生に失敗、Web Speechへフォールバック:', err);
    await speak(FIRST_QUESTION);
  }
}

/**
 * 精のせりふ音声を再生する。サーバーTTSが無ければWeb Speechにフォールバック。
 *
 * HTMLAudioElement(new Audio())はiOS Safariでユーザージェスチャー外の
 * play() が不規則に拒否され、マイク録音と交互に使うと「鳴ったり鳴らなかったり」
 * になるため、解錠済みの共有AudioContext(WebAudio)で再生する。
 */
function playQuestion(resp: TalkNextResponse): Promise<void> {
  if (resp.questionAudioBase64) {
    cancelSpeech();
    const blob = base64ToBlob(resp.questionAudioBase64, resp.questionAudioMime || 'audio/wav');
    return playAudioBlob(blob).catch((err) => {
      console.error('[talk] せりふ音声の再生に失敗、Web Speechへフォールバック:', err);
      return speak(resp.question);
    });
  }
  return speak(resp.question);
}

/**
 * S2: 対話画面(このアプリの心臓部)。
 * えほんの精が質問し、子どもは「マイク(タップで録音開始→タップで送信)」でも
 * 「選択肢タップ」でも答えられる。
 */
export function TalkScreen({ onDone, onQuit }: TalkScreenProps) {
  const [history, setHistory] = useState<TalkTurn[]>([]);
  const [current, setCurrent] = useState<TalkNextResponse | null>(null);
  const [busy, setBusy] = useState(true); // サーバー待ち(精が考え中)
  const [recording, setRecording] = useState(false); // 録音中(トグル)
  const [failCount, setFailCount] = useState(0);
  const [micDisabled, setMicDisabled] = useState(false); // マイク権限拒否時
  const [error, setError] = useState(false);

  const recorder = useRecorder();
  const startedRef = useRef(false);
  const historyRef = useRef<TalkTurn[]>([]);
  const currentRef = useRef<TalkNextResponse | null>(null);
  const lastAnswerRef = useRef<TalkNextRequest['answer']>(undefined);
  const doneRef = useRef(false);
  // 開始/停止の非同期処理中に連打されても二重実行しないためのガード
  const micBusyRef = useRef(false);
  // 「ひとつまえ」用: 回答済みの各質問のレスポンスを積む(history と同じ長さ)
  const responseStackRef = useRef<TalkNextResponse[]>([]);

  const stopVoice = useCallback(() => {
    stopAudioPlayback();
    cancelSpeech();
  }, []);

  /** 1ターン送信: answer未指定なら最初の質問(または同じ質問の言い直し)をもらう */
  const sendTurn = useCallback(
    async (answer: TalkNextRequest['answer']) => {
      if (doneRef.current) return;
      lastAnswerRef.current = answer;
      setBusy(true);
      setError(false);
      stopVoice();
      try {
        const resp = await talkNext({
          history: historyRef.current,
          answer,
          failCount,
        });

        // 答えが確定したら履歴に積む(聞き返しのときは積まない)
        if (answer && !resp.retry && currentRef.current) {
          const turn: TalkTurn = {
            question: currentRef.current.question,
            answer: resp.answerText ?? answer.text ?? '',
          };
          historyRef.current = [...historyRef.current, turn];
          setHistory(historyRef.current);
          // 「ひとつまえ」で戻れるよう、いま答えた質問のレスポンスを積む
          responseStackRef.current = [...responseStackRef.current, currentRef.current];
        }
        setFailCount((prev) => (resp.retry ? prev + 1 : 0));

        currentRef.current = resp;
        setCurrent(resp);
        setBusy(false);

        const playback = playQuestion(resp);
        if (resp.done) {
          doneRef.current = true;
          // 最後のよろこびのせりふを聞かせてから次へ
          void playback.then(() => onDone(historyRef.current));
        }
      } catch {
        setBusy(false);
        setError(true);
      }
    },
    [failCount, onDone, stopVoice],
  );

  // 1問目は固定なのでサーバーを呼ばず、待ち時間ゼロで表示する
  // (StrictModeの二重実行を防ぐ)
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    currentRef.current = FIRST_RESPONSE;
    setCurrent(FIRST_RESPONSE);
    setBusy(false);
    void playFirstQuestion();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 画面を離れるとき音声を止める
  useEffect(() => stopVoice, [stopVoice]);

  // --- マイク(タップで録音開始 → もう一度タップで終了・送信のトグル方式) ---
  // 押しっぱなし方式はiOS Safariのポインタイベントが不安定なため使わない。
  // 状態はrecordingの1つだけ。clickイベントなのでレースが起きない素直な実装。
  const toggleMic = async () => {
    if (micBusyRef.current || doneRef.current) return;
    micBusyRef.current = true;
    try {
      if (recording) {
        // 2回目のタップ: 録音終了 → 自動送信
        setRecording(false);
        playSound('tap');
        const result = await recorder.stop();
        if (!result) return; // 何も録れていなければ無視(次のタップでやり直せる)
        const audioBase64 = await blobToBase64(result.blob);
        void sendTurn({ audioBase64, audioMime: result.mime });
      } else {
        // 1回目のタップ: 録音開始
        if (busy) return;
        stopVoice(); // 精の声を録音に混ぜない
        playSound('tap');
        const ok = await recorder.start();
        if (!ok) {
          setMicDisabled(true); // 権限拒否 → 以後はタップ方式のみで進める
          return;
        }
        setRecording(true);
      }
    } finally {
      micBusyRef.current = false;
    }
  };

  const tapChoice = (label: string) => {
    if (busy || doneRef.current) return;
    // 録音中に選択肢をタップしたら、録音は破棄してタップの答えを優先する
    if (recording) {
      recorder.cancel();
      setRecording(false);
    }
    playSound('tap');
    void sendTurn({ text: label });
  };

  /** ひとつまえの質問に戻り、直前の回答を取り消してやり直す */
  const goBack = () => {
    if (busy || doneRef.current) return;
    const stack = responseStackRef.current;
    if (stack.length === 0) return;
    if (recording) {
      recorder.cancel();
      setRecording(false);
    }
    playSound('tap');
    stopVoice();
    const prev = stack[stack.length - 1];
    responseStackRef.current = stack.slice(0, -1);
    historyRef.current = historyRef.current.slice(0, -1);
    setHistory(historyRef.current);
    setFailCount(0);
    setError(false);
    currentRef.current = prev;
    setCurrent(prev);
    // 戻った質問を読み直す(1問目は固定音声)
    if (prev === FIRST_RESPONSE) void playFirstQuestion();
    else void playQuestion(prev);
  };

  const answeredCount = history.length;
  const expression: FairyExpression = busy
    ? 'thinking'
    : error
      ? 'surprised'
      : (current?.expression ?? 'normal');
  const bigChoices = failCount >= 3 || micDisabled; // 失敗続き・マイク不可なら選択肢を前面に

  return (
    <div className="screen talk-screen has-art-bg">
      <ArtBg src={ART.bgTalk} />
      <header className="talk-header">
        {/* ひとつまえに戻る(1問目では戻り先がないので表示しない) */}
        {history.length > 0 && !current?.done ? (
          <button
            className="talk-back pressable"
            onClick={goBack}
            disabled={busy}
            aria-label="ひとつまえの しつもんに もどる"
          >
            <span className="talk-back-icon" aria-hidden>
              ↩️
            </span>
            <span className="talk-back-label">ひとつまえ</span>
          </button>
        ) : null}
        {/* 進捗: 数字が読めなくても分かる花の数 + 補助テキスト */}
        <div
          className="talk-progress"
          aria-label={`あと${Math.max(QUESTION_TARGET - answeredCount, 0)}こ`}
        >
          {Array.from({ length: QUESTION_TARGET }, (_, i) => (
            <span
              key={i}
              className={`talk-progress-flower${i < answeredCount ? ' is-filled' : ''}`}
              aria-hidden
            >
              🌸
            </span>
          ))}
          <span className="talk-progress-text">
            {current?.done ? 'できた!' : `あと ${Math.max(QUESTION_TARGET - answeredCount, 0)} こ`}
          </span>
        </div>
        <button className="talk-quit pressable" onClick={onQuit} aria-label="やめる">
          ✕
        </button>
      </header>

      {/* えほんの精 */}
      <div className={`talk-fairy${busy ? ' is-thinking' : ''}`}>
        <img
          className="talk-fairy-img"
          src={FAIRY_IMAGES[expression]}
          alt="えほんの精"
          draggable={false}
        />
      </div>

      {/* 質問文(音声でも読み上げる) */}
      <div className="talk-question" aria-live="polite">
        {error ? (
          <>
            <p className="talk-question-text">えほんのせいに こえが とどかなかったみたい</p>
            <button
              className="talk-retry pressable"
              onClick={() => void sendTurn(lastAnswerRef.current)}
            >
              もういちど
            </button>
          </>
        ) : busy ? (
          <p className="talk-question-text talk-question-thinking">かんがえちゅう…</p>
        ) : (
          <p className="talk-question-text">{current?.question}</p>
        )}
      </div>

      {/* 答え方: マイク(タップで開始/終了) + 選択肢タップ。常に両方使える */}
      {!current?.done && (
        <div className={`talk-answers${bigChoices ? ' talk-answers--big' : ''}`}>
          {!micDisabled && (
            <button
              className={`talk-mic pressable${recording ? ' is-recording' : ''}`}
              onClick={() => void toggleMic()}
              onContextMenu={(e) => e.preventDefault()}
              disabled={busy && !recording}
              aria-pressed={recording}
              aria-label={recording ? 'おしたら おわり' : 'おして おはなしする'}
            >
              <span className="talk-mic-icon" aria-hidden>
                {recording ? '🔴' : '🎤'}
              </span>
              <span className="talk-mic-label">
                {recording ? 'きいてるよ… おしたら おくるよ' : 'おして はなす'}
              </span>
            </button>
          )}

          <div className="talk-choices">
            {(current?.choices ?? []).map((c) => (
              <button
                key={c.label}
                className="talk-choice pressable"
                onClick={() => tapChoice(c.label)}
                disabled={busy}
              >
                <span className="talk-choice-emoji" aria-hidden>
                  {c.emoji}
                </span>
                <span className="talk-choice-label">{c.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
