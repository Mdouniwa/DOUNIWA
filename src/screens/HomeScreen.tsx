import { useEffect, useState } from 'react';
import type { Navigate } from '../routes';
import type { Book } from '../types';
import { getAllBooks, touchBook } from '../lib/db';
import { BookCard } from '../components/BookCard';
import './HomeScreen.css';

interface HomeScreenProps {
  navigate: Navigate;
}

/** ホーム: 絵本カード2列 + 「つくる」導線。直近閲覧が先頭 */
export function HomeScreen({ navigate }: HomeScreenProps) {
  const [books, setBooks] = useState<Book[]>([]);

  useEffect(() => {
    void getAllBooks().then(setBooks);
  }, []);

  const openBook = (book: Book) => {
    void touchBook(book.id);
    navigate({ name: 'player', bookId: book.id });
  };

  return (
    <div className="screen home-screen">
      <header className="home-header">
        <h1 className="home-title">
          <span aria-hidden>📖</span> しゃべるえほん
        </h1>
      </header>

      <div className="home-grid">
        <button
          className="home-create-card pressable"
          onClick={() => navigate({ name: 'create' })}
        >
          <span className="home-create-icon" aria-hidden>
            ＋
          </span>
          <span className="home-create-label">つくる</span>
        </button>

        {books.map((book) => (
          <BookCard key={book.id} book={book} onClick={() => openBook(book)} />
        ))}
      </div>

      {books.length === 0 && (
        <p className="home-empty">「つくる」から さいしょの えほんを つくろう!</p>
      )}
    </div>
  );
}
