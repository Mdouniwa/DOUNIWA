import { useEffect, useRef, useState } from 'react';
import type { Navigate } from '../routes';
import type { Book, Page, Settings } from '../types';
import { getBook, getPagesForBook, getSettings } from '../lib/db';
import { usePagePlayer } from '../hooks/usePagePlayer';
import { useDebouncedTap } from '../hooks/useDebouncedTap';
import { useBlobUrl } from '../hooks/useBlobUrl';
import { playSound } from '../lib/soundEffects';
import './PlayerScreen.css';

interface PlayerScreenProps {
  bookId: string;
  navigate: Navigate;
}

/**
 * ページめくりアニメーションの長さ。
 * 見た目のためだけの値で、ページ送りロジック(index切替・ナレーション排他制御)には
 * 影響しない。連打対策のデバウンスだけ、この時間に合わせて延長している。
 */
const PAGE_TURN_MS = 520;

interface TurnLeaf {
  key: number;
  dir: 'next' | 'prev';
  url: string;
}

/** 再生画面: フルスクリーン、巨大◀▶、画像タップで効果音、ナレーション自動再生 */
export function PlayerScreen({ bookId, navigate }: PlayerScreenProps) {
  const [book, setBook] = useState<Book | null>(null);
  const [pages, setPages] = useState<Page[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [index, setIndex] = useState(0);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const [b, s] = await Promise.all([getBook(bookId), getSettings()]);
      if (cancelled) return;
      if (!b) {
        setLoaded(true);
        return;
      }
      const p = await getPagesForBook(b);
      if (cancelled) return;
      setBook(b);
      setPages(p);
      setSettings(s);
      setLoaded(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [bookId]);

  const page = pages[index] ?? null;
  const imageUrl = useBlobUrl(page?.imageBlob);
  const { stopAll } = usePagePlayer(page, settings);

  // ページめくりの見た目(ビジュアル専用レイヤー。ページ送りロジックには手を入れない)
  const [turn, setTurn] = useState<TurnLeaf | null>(null);
  const turnKeyRef = useRef(0);

  // アニメーション中に差し替えられる元画像は、表示用hookのURLとはライフサイクルを
  // 分離した自前のスナップショットを使う(差し替わった瞬間にrevokeされるのを避けるため)
  useEffect(() => {
    if (!turn) return;
    const timer = window.setTimeout(() => setTurn(null), PAGE_TURN_MS);
    return () => {
      window.clearTimeout(timer);
      URL.revokeObjectURL(turn.url);
    };
  }, [turn]);

  // ページ送り(アニメーション時間に合わせてデバウンスし、めくり中の連打を無視する)
  const goTo = useDebouncedTap((delta: -1 | 1) => {
    const fromPage = pages[index];
    const toIndex = Math.max(0, Math.min(pages.length - 1, index + delta));
    if (toIndex !== index && fromPage) {
      turnKeyRef.current += 1;
      setTurn({
        key: turnKeyRef.current,
        dir: delta === 1 ? 'next' : 'prev',
        url: URL.createObjectURL(fromPage.imageBlob),
      });
    }
    setIndex(toIndex);
  }, PAGE_TURN_MS);

  const exit = () => {
    stopAll();
    navigate({ name: 'home' });
  };

  // 画像タップ: 効果音を並行再生(ナレーションは止めない)
  const tapImage = () => {
    if (page?.soundEffect) playSound(page.soundEffect);
  };

  if (!loaded) {
    return <div className="player-screen player-loading">よみこみちゅう…</div>;
  }

  if (!book || pages.length === 0) {
    return (
      <div className="player-screen player-loading">
        <p>えほんが みつからないよ</p>
        <button className="player-close" onClick={exit} aria-label="ホームへもどる">
          ✕
        </button>
      </div>
    );
  }

  return (
    <div className="player-screen">
      <div className="player-page-frame">
        <span className="player-gutter" aria-hidden />
        <button className="player-image-area" onClick={tapImage} aria-label="効果音を鳴らす">
          {imageUrl && <img className="player-image" src={imageUrl} alt="" draggable={false} />}
        </button>
        {turn && (
          <div
            key={turn.key}
            className={`player-turn-leaf player-turn-leaf--${turn.dir}`}
            aria-hidden
          >
            <img src={turn.url} alt="" draggable={false} />
          </div>
        )}
      </div>

      <button
        className="player-nav player-nav--left pressable"
        onClick={() => goTo(-1)}
        disabled={index === 0}
        aria-label="まえのページ"
      >
        ◀
      </button>
      <button
        className="player-nav player-nav--right pressable"
        onClick={() => goTo(1)}
        disabled={index === pages.length - 1}
        aria-label="つぎのページ"
      >
        ▶
      </button>

      <button className="player-close" onClick={exit} aria-label="ホームへもどる">
        ✕
      </button>

      <div className="player-dots" aria-hidden>
        {pages.map((p, i) => (
          <span key={p.id} className={`player-dot ${i === index ? 'player-dot--current' : ''}`} />
        ))}
      </div>
    </div>
  );
}
