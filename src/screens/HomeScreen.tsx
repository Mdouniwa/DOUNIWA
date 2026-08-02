import { useEffect, useState } from 'react';
import type { Navigate } from '../routes';
import type { Book } from '../types';
import { getAllBooks, touchBook } from '../lib/db';
import { BookCard } from '../components/BookCard';
import { ArtBg } from '../components/ArtBg';
import { DecoSprinkles, type DecoItem } from '../components/DecoSprinkles';
import { ART, FAIRY_IMAGES } from '../lib/artAssets';
import { useLongPress } from '../hooks/useLongPress';
import { playSound } from '../lib/soundEffects';
import './HomeScreen.css';

interface HomeScreenProps {
  navigate: Navigate;
}

/** 余白に散りばめる装飾(タップ領域の外側の四隅・辺に寄せる) */
const HOME_DECO: DecoItem[] = [
  { name: 'bird', style: { top: '10px', left: '4px', width: '64px', transform: 'rotate(-8deg)' } },
  { name: 'balloon', style: { top: '86px', right: '-6px', width: '76px', transform: 'rotate(6deg)' }, tier: 2 },
  { name: 'mushroom', style: { bottom: '8px', left: '-4px', width: '70px', transform: 'rotate(-6deg)' } },
  { name: 'rabbit', style: { bottom: '4px', right: '2px', width: '72px', transform: 'rotate(5deg)' }, tier: 2 },
  { name: 'star', style: { top: '46%', left: '-10px', width: '52px', transform: 'rotate(-14deg)' }, tier: 3 },
  { name: 'cloud', style: { top: '38%', right: '-14px', width: '84px' }, tier: 3 },
];

/** 0冊のとき、えほんの精のまわりに置く装飾 */
const HERO_DECO: DecoItem[] = [
  { name: 'elephant', style: { bottom: '18%', left: '2%', width: '88px', transform: 'rotate(-5deg)' } },
  { name: 'bear', style: { bottom: '16%', right: '3%', width: '84px', transform: 'rotate(6deg)' } },
  { name: 'train', style: { bottom: '2%', left: '14%', width: '96px' }, tier: 2 },
  { name: 'ship', style: { bottom: '3%', right: '12%', width: '88px', transform: 'rotate(-4deg)' }, tier: 2 },
  { name: 'rainbow', style: { top: '2%', left: '6%', width: '92px', transform: 'rotate(-6deg)' }, tier: 2 },
  { name: 'flower', style: { top: '6%', right: '8%', width: '60px', transform: 'rotate(10deg)' }, tier: 3 },
];

/** ホーム: 絵本カード2列 + 「つくる」導線。直近閲覧が先頭 */
export function HomeScreen({ navigate }: HomeScreenProps) {
  const [books, setBooks] = useState<Book[]>([]);
  const [loaded, setLoaded] = useState(false);

  // 親モード入口: 画面隅を3秒長押し(子どもが偶然開かないように)
  const parentEntry = useLongPress(() => navigate({ name: 'parent' }), 3000);

  useEffect(() => {
    void getAllBooks().then((list) => {
      setBooks(list);
      setLoaded(true);
    });
  }, []);

  const openBook = (book: Book) => {
    playSound('tap');
    void touchBook(book.id);
    navigate({ name: 'player', bookId: book.id });
  };

  const openCreate = () => {
    playSound('tap');
    navigate({ name: 'create' });
  };

  const empty = loaded && books.length === 0;

  return (
    <div className="screen home-screen has-art-bg">
      <ArtBg src={ART.bgHome} />
      <DecoSprinkles items={empty ? HOME_DECO.concat(HERO_DECO) : HOME_DECO} />

      <header className="home-header">
        <h1 className="home-title">
          <img className="home-logo" src={ART.logo} alt="しゃべるえほん" draggable={false} />
        </h1>
        <div className="home-parent-corner" {...parentEntry} aria-label="おやモード(3秒長押し)" />
      </header>

      {empty ? (
        /* 空状態: えほんの精が「はじめてのえほん」へ誘う */
        <div className="home-hero">
          <img
            className="home-hero-fairy"
            src={FAIRY_IMAGES.cheer}
            alt="えほんの精"
            draggable={false}
          />
          <p className="home-hero-text">はじめての えほんを つくろう!</p>
          <button className="home-hero-create pressable" onClick={openCreate}>
            <span className="home-create-icon" aria-hidden>
              ＋
            </span>
            <span className="home-create-label">つくる</span>
          </button>
        </div>
      ) : (
        <div className="home-grid">
          <button className="home-create-card pressable" onClick={openCreate}>
            <span className="home-create-icon" aria-hidden>
              ＋
            </span>
            <span className="home-create-label">つくる</span>
          </button>

          {books.map((book) => (
            <BookCard key={book.id} book={book} framed onClick={() => openBook(book)} />
          ))}
        </div>
      )}
    </div>
  );
}
