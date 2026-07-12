import { useCallback, useEffect, useState } from 'react';
import type { Navigate } from '../routes';
import type { Book, Page } from '../types';
import {
  deleteBookWithPages,
  getAllBooks,
  getPagesForBook,
  putBook,
  putPage,
} from '../lib/db';
import { BookCard } from '../components/BookCard';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { PageThumb } from './create/PageThumb';
import './ParentScreen.css';

interface ParentScreenProps {
  navigate: Navigate;
}

/** 親モード: 絵本の削除(2段階確認)・ページ並び替え・表紙変更・キャプション編集 */
export function ParentScreen({ navigate }: ParentScreenProps) {
  const [books, setBooks] = useState<Book[]>([]);
  const [selected, setSelected] = useState<Book | null>(null);

  const reload = useCallback(async () => {
    const all = await getAllBooks();
    setBooks(all);
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <div className="screen parent-screen">
      <header className="parent-header">
        <button
          className="parent-back pressable"
          onClick={() => (selected ? setSelected(null) : navigate({ name: 'home' }))}
        >
          ← {selected ? 'いちらんへ' : 'ホームへ'}
        </button>
        <h1 className="parent-title">おやモード</h1>
        <span />
      </header>

      {!selected ? (
        <>
          {books.length === 0 && <p className="parent-empty">絵本はまだありません</p>}
          <div className="parent-grid">
            {books.map((book) => (
              <BookCard key={book.id} book={book} onClick={() => setSelected(book)} />
            ))}
          </div>
        </>
      ) : (
        <BookEditor
          book={selected}
          onBookChange={(b) => {
            setSelected(b);
            void reload();
          }}
          onDeleted={() => {
            setSelected(null);
            void reload();
          }}
        />
      )}
    </div>
  );
}

interface BookEditorProps {
  book: Book;
  onBookChange: (book: Book) => void;
  onDeleted: () => void;
}

function BookEditor({ book, onBookChange, onDeleted }: BookEditorProps) {
  const [pages, setPages] = useState<Page[]>([]);
  // 削除は2段階確認: confirm1 → confirm2 → 実行
  const [deleteStep, setDeleteStep] = useState<0 | 1 | 2>(0);

  useEffect(() => {
    let cancelled = false;
    void getPagesForBook(book).then((p) => {
      if (!cancelled) setPages(p);
    });
    return () => {
      cancelled = true;
    };
  }, [book]);

  const persistBook = async (updated: Book) => {
    updated.updatedAt = Date.now();
    await putBook(updated);
    onBookChange(updated);
  };

  const movePage = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= book.pageIds.length) return;
    const pageIds = [...book.pageIds];
    const [id] = pageIds.splice(index, 1);
    pageIds.splice(target, 0, id);
    void persistBook({ ...book, pageIds });
    setPages((prev) => {
      const next = [...prev];
      const [pg] = next.splice(index, 1);
      next.splice(target, 0, pg);
      return next;
    });
  };

  const setCover = (pageId: string) => {
    void persistBook({ ...book, coverImageId: pageId });
  };

  const setTitle = (title: string) => {
    onBookChange({ ...book, title });
  };
  const commitTitle = () => {
    void persistBook({ ...book });
  };

  const setCaption = (pageId: string, captionText: string) => {
    setPages((prev) => prev.map((p) => (p.id === pageId ? { ...p, captionText } : p)));
  };
  const commitCaption = (pageId: string) => {
    const page = pages.find((p) => p.id === pageId);
    if (page) void putPage(page);
  };

  const doDelete = async () => {
    await deleteBookWithPages(book.id);
    setDeleteStep(0);
    onDeleted();
  };

  return (
    <div className="parent-editor">
      <label className="parent-field">
        タイトル
        <input
          className="parent-input"
          type="text"
          value={book.title}
          maxLength={30}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={commitTitle}
        />
      </label>

      <h2 className="parent-section-title">ページ(並び替え / 表紙 / よみあげ文)</h2>
      <div className="parent-pages">
        {pages.map((page, i) => (
          <div key={page.id} className="parent-page-row">
            <span className="parent-page-number">{i + 1}</span>
            <div className="parent-page-thumb">
              <PageThumb blob={page.thumbBlob} />
              {book.coverImageId === page.id && <span className="parent-cover-badge">表紙</span>}
            </div>
            <div className="parent-page-main">
              <textarea
                className="parent-caption"
                placeholder="よみあげ文(録音がないときにTTSで読まれます)"
                value={page.captionText}
                rows={2}
                onChange={(e) => setCaption(page.id, e.target.value)}
                onBlur={() => commitCaption(page.id)}
              />
              <div className="parent-page-actions">
                <button
                  className="parent-mini-button pressable"
                  disabled={i === 0}
                  onClick={() => movePage(i, -1)}
                >
                  ← まえへ
                </button>
                <button
                  className="parent-mini-button pressable"
                  disabled={i === pages.length - 1}
                  onClick={() => movePage(i, 1)}
                >
                  うしろへ →
                </button>
                <button
                  className="parent-mini-button pressable"
                  disabled={book.coverImageId === page.id}
                  onClick={() => setCover(page.id)}
                >
                  表紙にする
                </button>
                <span className="parent-page-meta">
                  {page.audioBlob ? '🎤 録音あり' : page.captionText.trim() ? '💬 TTS' : '🔇 無音'}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="parent-danger">
        <button className="parent-delete pressable" onClick={() => setDeleteStep(1)}>
          この絵本を削除する
        </button>
      </div>

      <ConfirmDialog
        open={deleteStep === 1}
        title="絵本を削除しますか?"
        message={`「${book.title}」とすべてのページ・録音が消えます。`}
        confirmLabel="削除へすすむ"
        danger
        onConfirm={() => setDeleteStep(2)}
        onCancel={() => setDeleteStep(0)}
      />
      <ConfirmDialog
        open={deleteStep === 2}
        title="本当に削除しますか?"
        message="この操作は取り消せません。"
        confirmLabel="完全に削除する"
        danger
        onConfirm={() => void doDelete()}
        onCancel={() => setDeleteStep(0)}
      />
    </div>
  );
}
