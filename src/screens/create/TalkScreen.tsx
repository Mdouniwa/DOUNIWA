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
 * 精のせりふ音声を再生する。サーバーTTSが無ければWeb Speechにフォールバック。
 *
 * HTMLAudioElement(new Audio())はiOS Safariでユーザージェスチャー外の
 * play() が不規則に拒否され、マイク録音と交互に使うと「鳴ったり鳴らなかったり」
 * になるため、解錠済みの共有AudioContext(WebAudio)で再生する。
 */
function playQuestion(resp: TalkNextResponse): Promise<void> {
  if (resp.questionAudioBase64) {
    cancelSpeech(); // 選択肢ラベルの読み上げが残っていたら止めてから精のこえを流す
    const blob = base64ToBlob(resp.questionAudioBase64, resp.questionAudioMime || 'audio/wav');
    return playAudioBlob(blob).catch(() => speak(resp.question));
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
  const startedRef = useRef(false);
  const historyRef = useRef<TalkTurn[]>([]);
  const currentRef = useRef<TalkNextResponse | null>(null);
  const lastAnswerRef = useRef<TalkNextRequest['answer']>(undefined);
  const doneRef = useRef(false);
  // マイクの押下状態はrender間で正確に追う必要があるためref
  // (getUserMedia待ちの間にpointerupが来るとstateのクロージャでは取りこぼす)
  const pressedRef = useRef(false);
  const listeningRef = useRef(false);
  const recordStartRef = useRef(0);

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

  /** 録音を終了し、十分な長さがあれば送信する */
  const finishRecording = async () => {
    if (!listeningRef.current) return;
    listeningRef.current = false;
    setListening(false);
    // 一瞬だけ触れた等のごく短い録音は破棄(無音送信で聞き返しになるのを防ぐ)
    if (Date.now() - recordStartRef.current < 250) {
      recorder.cancel();
      return;
    }
    const result = await recorder.stop();
    if (!result) return; // 何も録れていなければ無視
    playSound('tap');
    const audioBase64 = await blobToBase64(result.blob);
    void sendTurn({ audioBase64, audioMime: result.mime });
  };

  const micDown = async () => {
    if (busy || pressedRef.current || listeningRef.current || doneRef.current) return;
    pressedRef.current = true;
    stopVoice(); // 精の声を録音に混ぜない
    const ok = await recorder.start();
    if (!ok) {
      pressedRef.current = false;
      setMicDisabled(true); // 権限拒否 → 以後はタップ方式のみで進める
      return;
    }
    recordStartRef.current = Date.now();
    listeningRef.current = true;
    setListening(true);
    // getUserMedia待ちの間に指が離れていた場合はここで終了する
    // (pointerupが先に来ると micUp 側では録音開始前のため処理できない)
    if (!pressedRef.current) {
      void finishRecording();
    }
  };

  const micUp = () => {
    if (!pressedRef.current) return;
    pressedRef.current = false;
    // 録音開始前(getUserMedia待ち)なら micDown 側が終了処理を引き継ぐ
    if (!listeningRef.current) return;
    void finishRecording();
  };

  const tapChoice = (label: string) => {
    if (busy || doneRef.current) return;
    playSound('tap');
    // 選んだことばをローカルTTSで読み上げる(文字が読めない子への即時フィードバック)。
    // sendTurn冒頭のstopVoice()に消されないよう、sendTurn開始後に呼ぶ。
    // 進行は読み上げを待たない(サーバー応答が来たら精のこえが引き継ぐ)。
    void sendTurn({ text: label });
    void speak(label);
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
            <p className="talk-question-text">えほんのせいの こえが とどかなかったよ</p>
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
              onPointerUp={micUp}
              onPointerLeave={micUp}
              onPointerCancel={micUp}
              onLostPointerCapture={micUp}
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
