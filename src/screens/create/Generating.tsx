import { useEffect, useRef, useState } from 'react';
import { generateBook } from '../../lib/generateBook';
import { iconEmoji } from '../../lib/icons';
import type { DraftPage } from './draft';
import { BigButton } from '../../components/BigButton';
import './generating.css';

interface GeneratingProps {
  iconKeywords: string[];
  onDone: (title: string, pages: DraftPage[]) => void;
  onBack: () => void;
}

const MESSAGES = [
  'まほうつかいが えほんを つくっているよ…',
  'おはなしを かんがえているよ…',
  'えを かいているよ…',
  'こえを ふきこんでいるよ…',
  'もうすこしで できあがり…',
];

/** Step2: 生成中のローディング画面。API呼び出し中は選んだアイコンがくるくる回る */
export function Generating({ iconKeywords, onDone, onBack }: GeneratingProps) {
  const [error, setError] = useState<string | null>(null);
  const [msgIndex, setMsgIndex] = useState(0);
  // 生成は高コストなので、StrictModeの二重実行や再送信を必ず防ぐ
  const startedRef = useRef(false);

  const run = () => {
    setError(null);
    void generateBook(iconKeywords)
      .then((book) => onDone(book.title, book.pages))
      .catch(() => setError('えほんが つくれなかったよ。もういちど ためしてね。'));
  };

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // メッセージを順番に切り替えて退屈させない
  useEffect(() => {
    if (error) return;
    const timer = window.setInterval(() => {
      setMsgIndex((i) => (i + 1) % MESSAGES.length);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [error]);

  if (error) {
    return (
      <div className="create-step generating-step">
        <div className="generating-error-emoji" aria-hidden>
          😢
        </div>
        <p className="generating-error-text">{error}</p>
        <div className="generating-error-actions">
          <BigButton color="ghost" silent onClick={onBack}>
            ← もどる
          </BigButton>
          <BigButton
            color="primary"
            silent
            onClick={() => {
              startedRef.current = true;
              run();
            }}
          >
            もういちど
          </BigButton>
        </div>
      </div>
    );
  }

  return (
    <div className="create-step generating-step">
      <div className="generating-orbit" aria-hidden>
        <div className="generating-center">✨</div>
        {iconKeywords.map((k, i) => (
          <span
            key={k}
            className="generating-icon"
            style={{
              transform: `rotate(${(360 / iconKeywords.length) * i}deg) translateY(-110px)`,
            }}
          >
            <span
              style={{ transform: `rotate(-${(360 / iconKeywords.length) * i}deg)`, display: 'inline-block' }}
            >
              {iconEmoji(k)}
            </span>
          </span>
        ))}
      </div>
      <p className="generating-message">{MESSAGES[msgIndex]}</p>
      <p className="generating-hint">ちょっと まっててね(30びょうくらい)</p>
    </div>
  );
}
