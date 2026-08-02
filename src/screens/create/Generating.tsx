import { useEffect, useRef, useState } from 'react';
import { generateBookFromTalk } from '../../lib/generateBook';
import type { BookJobStatus, TalkTurn } from '../../lib/talkApi';
import type { Draft, DraftPage } from './draft';
import { BigButton } from '../../components/BigButton';
import { ArtBg } from '../../components/ArtBg';
import { ART, FAIRY_IMAGES } from '../../lib/artAssets';
import './generating.css';

interface GeneratingProps {
  conversation: TalkTurn[];
  onDone: (title: string, pages: DraftPage[], characterRef: Draft['characterRef']) => void;
  onBack: () => void;
}

/** ジョブ状況ごとの、精のようすとメッセージ */
const STATUS_VIEW: Record<BookJobStatus, { fairy: string; message: string }> = {
  story: { fairy: FAIRY_IMAGES.thinking, message: 'おはなしを かんがえているよ…' },
  character: { fairy: FAIRY_IMAGES.thinking, message: 'しゅじんこうを かいているよ…' },
  pages: { fairy: FAIRY_IMAGES.normal, message: 'えを かいているよ…' },
  audio: { fairy: FAIRY_IMAGES.happy, message: 'こえを ふきこんでいるよ…' },
  done: { fairy: FAIRY_IMAGES.cheer, message: 'できあがり!' },
  error: { fairy: FAIRY_IMAGES.surprised, message: '' },
};

/**
 * S3: 生成中画面。えほんの精が絵本を作っている間、
 * 子どもが答えた内容が順に浮かび上がり、退屈させない。
 */
export function Generating({ conversation, onDone, onBack }: GeneratingProps) {
  const [error, setError] = useState(false);
  const [status, setStatus] = useState<BookJobStatus>('story');
  const [progress, setProgress] = useState(0.05);
  const [answerIndex, setAnswerIndex] = useState(0);
  // 生成は高コストなので、StrictModeの二重実行や再送信を必ず防ぐ
  const startedRef = useRef(false);

  const answers = conversation.map((t) => t.answer).filter((a) => a.trim());

  const run = () => {
    setError(false);
    setStatus('story');
    setProgress(0.05);
    void generateBookFromTalk(conversation, (s, p) => {
      setStatus(s);
      setProgress(p);
    })
      .then((book) => onDone(book.title, book.pages, book.characterRef))
      .catch(() => setError(true));
  };

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 子どもの答えを順番に浮かび上がらせる
  useEffect(() => {
    if (error || answers.length === 0) return;
    const timer = window.setInterval(() => {
      setAnswerIndex((i) => (i + 1) % answers.length);
    }, 2800);
    return () => window.clearInterval(timer);
  }, [error, answers.length]);

  if (error) {
    return (
      <div className="screen generating-step has-art-bg">
        <ArtBg src={ART.bgTalk} veil="strong" />
        <img
          className="generating-fairy"
          src={STATUS_VIEW.error.fairy}
          alt="えほんの精"
          draggable={false}
        />
        <p className="generating-error-text">
          えほんが つくれなかったよ。
          <br />
          もういちど ためしてみてね。
        </p>
        <div className="generating-error-actions">
          <BigButton color="ghost" silent onClick={onBack}>
            ← もどる
          </BigButton>
          <BigButton color="primary" silent onClick={run}>
            もういちど
          </BigButton>
        </div>
      </div>
    );
  }

  const view = STATUS_VIEW[status];

  return (
    <div className="screen generating-step has-art-bg">
      <ArtBg src={ART.bgTalk} veil="strong" />
      <div className="generating-stage">
        <img className="generating-fairy" src={view.fairy} alt="えほんの精" draggable={false} />
        {answers.length > 0 && (
          <p key={answerIndex} className="generating-answer" aria-hidden>
            {answers[answerIndex]}…
          </p>
        )}
      </div>

      <p className="generating-message">{view.message}</p>

      <div
        className="generating-bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress * 100)}
      >
        <div className="generating-bar-fill" style={{ width: `${Math.round(progress * 100)}%` }}>
          <span className="generating-bar-star" aria-hidden>
            ✨
          </span>
        </div>
      </div>

      <p className="generating-hint">ちょっと まっててね(1ぷんくらい)</p>
    </div>
  );
}
