import { useCallback, useEffect, useRef, useState } from 'react';
import {
  talkNext,
  base64ToBlob,
  blobToBase64,
  QUESTION_TARGET,
  type FairyExpression,
  type TalkNextRequest,
  type TalkNextResponse,
  type TalkTurn,
} from '../../lib/talkApi';
import { speak, cancelSpeech } from '../../lib/tts';
import { playSound } from '../../lib/soundEffects';
import { useRecorder } from '../../hooks/useRecorder';
import { FAIRY_IMAGES } from '../../lib/artAssets';
import './talk.css';

interface TalkScreenProps {
  /** 対話が完了したとき、集めた対話ログを渡す */
  onDone: (conversation: TalkTurn[]) => void;
  /** やめる(ホームへ) */
  onQuit: () => void;
}

/** 精のせりふ音声を再生する。サーバーTTSが無ければWeb Speechにフォールバック */
function playQuestion(
  resp: TalkNextResponse,
  audioRef: { current: HTMLAudioElement | null },
): Promise<void> {
  if (resp.questionAudioBase64) {
    return new Promise((resolve) => {
      const blob = base64ToBlob(
        resp.questionAudioBase64!,
        resp.questionAudioMime || 'audio/wav',
      );
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      const finish = () => {
        URL.revokeObjectURL(url);
        resolve();
      };
      audio.onended = finish;
      audio.onerror = finish;
      // iOSで再生がブロックされたらWeb Speechにフォールバック
      audio.play().catch(() => {
        URL.revokeObjectURL(url);
        void speak(resp.question).then(resolve);
      });
    });
  }
  return speak(resp.question);
}

/**
 * S2: 対話画面(このアプリの心臓部)。
 * えほんの精が質問し、子どもは「押しっぱなしマイク」でも「選択肢タップ」でも答えられる。
 */
export function TalkScreen({ onDone, onQuit }: TalkScreenProps) {
  const [history, setHistory] = useState<TalkTurn[]>([]);
  const [current, setCurrent] = useState<TalkNextResponse | null>(null);
  const [busy, setBusy] = useState(true); // サーバー待ち(精が考え中)
  const [listening, setListening] = useState(false); // マイク押下中
  const [failCount, setFailCount] = useState(0);
  const [micDisabled, setMicDisabled] = useState(false); // マイク権限拒否時
  const [error, setError] = useState(false);

  const recorder = useRecorder();
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const startedRef = useRef(false);
  const historyRef = useRef<TalkTurn[]>([]);
  const currentRef = useRef<TalkNextResponse | null>(null);
  const lastAnswerRef = useRef<TalkNextRequest['answer']>(undefined);
  const doneRef = useRef(false);

  const stopVoice = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
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
        }
        setFailCount((prev) => (resp.retry ? prev + 1 : 0));

        currentRef.current = resp;
        setCurrent(resp);
        setBusy(false);

        const playback = playQuestion(resp, audioRef);
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

  // 最初の質問(StrictModeの二重実行を防ぐ)
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    void sendTurn(undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 画面を離れるとき音声を止める
  useEffect(() => stopVoice, [stopVoice]);

  // --- マイク(押している間だけ録音) ---
  const micDown = async () => {
    if (busy || listening || doneRef.current) return;
    stopVoice(); // 精の声を録音に混ぜない
    const ok = await recorder.start();
    if (!ok) {
      setMicDisabled(true); // 権限拒否 → 以後はタップ方式のみで進める
      return;
    }
    setListening(true);
  };

  const micUp = async () => {
    if (!listening) return;
    setListening(false);
    const result = await recorder.stop();
    if (!result) return; // 何も録れていない(一瞬だけ触れた等)は無視
    playSound('tap');
    const audioBase64 = await blobToBase64(result.blob);
    void sendTurn({ audioBase64, audioMime: result.mime });
  };

  const tapChoice = (label: string) => {
    if (busy || doneRef.current) return;
    playSound('tap');
    void sendTurn({ text: label });
  };

  const answeredCount = history.length;
  const expression: FairyExpression = busy ? 'thinking' : (current?.expression ?? 'normal');
  const bigChoices = failCount >= 3 || micDisabled; // 失敗続き・マイク不可なら選択肢を前面に

  return (
    <div className="screen talk-screen">
      <header className="talk-header">
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
            <p className="talk-question-text">せいの こえが とどかなかったよ</p>
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

      {/* 答え方: マイク(押しっぱなし) + 選択肢タップ。常に両方使える */}
      {!current?.done && (
        <div className={`talk-answers${bigChoices ? ' talk-answers--big' : ''}`}>
          {!micDisabled && (
            <button
              className={`talk-mic pressable${listening ? ' is-listening' : ''}`}
              onPointerDown={() => void micDown()}
              onPointerUp={() => void micUp()}
              onPointerLeave={() => void micUp()}
              onPointerCancel={() => void micUp()}
              onContextMenu={(e) => e.preventDefault()}
              disabled={busy && !listening}
              aria-label="おしてるあいだ おはなしできるよ"
            >
              <span className="talk-mic-icon" aria-hidden>
                🎤
              </span>
              <span className="talk-mic-label">{listening ? 'きいてるよ…' : 'おして はなす'}</span>
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
