import { useEffect, useState } from 'react';
import type { Book } from '../types';
import { THEME_EMOJI } from '../types';
import { getPage } from '../lib/db';
import { useBlobUrl } from '../hooks/useBlobUrl';
import './BookCard.css';

interface BookCardProps {
  book: Book;
  onClick: () => void;
}

/** ホーム・親モードで使う絵本カード(表紙サムネ+タイトル) */
export function BookCard({ book, onClick }: BookCardProps) {
  const [coverBlob, setCoverBlob] = useState<Blob | null>(null);

  useEffect(() => {
    let cancelled = false;
    const coverId = book.coverImageId ?? book.pageIds[0];
    if (!coverId) return;
    getPage(coverId).then((page) => {
      if (!cancelled && page) setCoverBlob(page.thumbBlob);
    });
    return () => {
      cancelled = true;
    };
  }, [book.coverImageId, book.pageIds]);

  const coverUrl = useBlobUrl(coverBlob);

  return (
    <button className="book-card pressable" onClick={onClick}>
      <div className="book-card__cover">
        {coverUrl ? (
          <img src={coverUrl} alt="" />
        ) : (
          <span className="book-card__placeholder">{THEME_EMOJI[book.theme]}</span>
        )}
      </div>
      <div className="book-card__title">{book.title || 'えほん'}</div>
    </button>
  );
}
