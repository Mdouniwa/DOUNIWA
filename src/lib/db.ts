import { openDB, type DBSchema, type IDBPDatabase } from 'idb';
import type { Book, Page, Settings } from '../types';
import { DEFAULT_SETTINGS } from '../types';

interface EhonDB extends DBSchema {
  books: {
    key: string;
    value: Book;
    indexes: { 'by-lastOpenedAt': number };
  };
  pages: {
    key: string;
    value: Page;
    indexes: { 'by-bookId': string };
  };
  settings: {
    key: string;
    value: Settings;
  };
}

let dbPromise: Promise<IDBPDatabase<EhonDB>> | null = null;

export function getDB(): Promise<IDBPDatabase<EhonDB>> {
  if (!dbPromise) {
    dbPromise = openDB<EhonDB>('ehon-db', 1, {
      upgrade(db) {
        const books = db.createObjectStore('books', { keyPath: 'id' });
        books.createIndex('by-lastOpenedAt', 'lastOpenedAt');
        const pages = db.createObjectStore('pages', { keyPath: 'id' });
        pages.createIndex('by-bookId', 'bookId');
        db.createObjectStore('settings');
      },
    });
  }
  return dbPromise;
}

/** 直近閲覧が先頭になるよう全絵本を取得 */
export async function getAllBooks(): Promise<Book[]> {
  const db = await getDB();
  const books = await db.getAll('books');
  return books.sort((a, b) => b.lastOpenedAt - a.lastOpenedAt);
}

export async function getBook(id: string): Promise<Book | undefined> {
  const db = await getDB();
  return db.get('books', id);
}

export async function putBook(book: Book): Promise<void> {
  const db = await getDB();
  await db.put('books', book);
}

export async function getPage(id: string): Promise<Page | undefined> {
  const db = await getDB();
  return db.get('pages', id);
}

export async function putPage(page: Page): Promise<void> {
  const db = await getDB();
  await db.put('pages', page);
}

/** book.pageIds の順序どおりにページを返す */
export async function getPagesForBook(book: Book): Promise<Page[]> {
  const db = await getDB();
  const tx = db.transaction('pages');
  const pages = await Promise.all(book.pageIds.map((id) => tx.store.get(id)));
  await tx.done;
  return pages.filter((p): p is Page => p !== undefined);
}

/** 絵本とページ一式を1トランザクションで保存 */
export async function createBookWithPages(book: Book, pages: Page[]): Promise<void> {
  const db = await getDB();
  const tx = db.transaction(['books', 'pages'], 'readwrite');
  await Promise.all([
    tx.objectStore('books').put(book),
    ...pages.map((p) => tx.objectStore('pages').put(p)),
  ]);
  await tx.done;
}

/** 絵本と紐づく全ページを1トランザクションでまとめて削除 */
export async function deleteBookWithPages(bookId: string): Promise<void> {
  const db = await getDB();
  const tx = db.transaction(['books', 'pages'], 'readwrite');
  const pageStore = tx.objectStore('pages');
  const pageKeys = await pageStore.index('by-bookId').getAllKeys(bookId);
  await Promise.all([
    tx.objectStore('books').delete(bookId),
    ...pageKeys.map((key) => pageStore.delete(key)),
  ]);
  await tx.done;
}

/** 閲覧時刻を更新(ホームの並び順用) */
export async function touchBook(bookId: string): Promise<void> {
  const db = await getDB();
  const book = await db.get('books', bookId);
  if (book) {
    book.lastOpenedAt = Date.now();
    await db.put('books', book);
  }
}

const SETTINGS_KEY = 'app';

export async function getSettings(): Promise<Settings> {
  const db = await getDB();
  const saved = await db.get('settings', SETTINGS_KEY);
  return { ...DEFAULT_SETTINGS, ...saved };
}

export async function saveSettings(settings: Settings): Promise<void> {
  const db = await getDB();
  await db.put('settings', settings, SETTINGS_KEY);
}
