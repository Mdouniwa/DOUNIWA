import { useState } from 'react';
import type { Draft } from './draft';
import type { Book, Page } from '../../types';
import { THEME_LABELS } from '../../types';
import { createBookWithPages } from '../../lib/db';
import { playSound } from '../../lib/soundEffects';
import { BigButton } from '../../components/BigButton';
import { PageThumb } from './PageThumb';

interface CoverSetupProps {
  draft: Draft;
  onChange: (patch: Partial<Draft>) => void;
  onSaved: () => void;
}

/** Step5: 表紙の写真1枚 + タイトル(入力はOS標準ディクテーション想定) */
export function CoverSetup({ draft, onChange, onSaved }: CoverSetupProps) {
  const [saving, setSaving] = useState(false);
  const coverPageId = draft.coverPageId ?? draft.pages[0]?.id ?? null;

  const save = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const now = Date.now();
      const bookId = crypto.randomUUID();
      const pages: Page[] = draft.pages.map((p) => ({
        id: p.id,
        bookId,
        imageBlob: p.imageBlob,
        thumbBlob: p.thumbBlob,
        captionText: p.captionText,
        audioBlob: p.audioBlob,
        audioMime: p.audioMime,
        soundEffect: p.soundEffect,
      }));
      const book: Book = {
        id: bookId,
        title: draft.title.trim() || THEME_LABELS[draft.theme],
        coverImageId: coverPageId,
        theme: draft.theme,
        pageIds: pages.map((p) => p.id),
        createdAt: now,
        updatedAt: now,
        lastOpenedAt: now,
      };
      await createBookWithPages(book, pages);
      playSound('success');
      onSaved();
    } catch {
      setSaving(false);
      alert('ほぞんに しっぱいしたよ。もういちど ためしてね。');
    }
  };

  return (
    <div className="create-step">
      <h2 className="create-step-title">ひょうしを つくろう</h2>

      <label className="cover-title-label">
        えほんの なまえ
        <input
          className="cover-title-input"
          type="text"
          value={draft.title}
          placeholder={THEME_LABELS[draft.theme]}
          maxLength={30}
          onChange={(e) => onChange({ title: e.target.value })}
        />
      </label>

      <p className="create-step-hint">ひょうしの しゃしんを えらんでね</p>
      <div className="cover-grid">
        {draft.pages.map((p) => (
          <button
            key={p.id}
            className={`cover-cell pressable ${p.id === coverPageId ? 'cover-cell--selected' : ''}`}
            onClick={() => onChange({ coverPageId: p.id })}
          >
            <PageThumb blob={p.thumbBlob} />
          </button>
        ))}
      </div>

      <div className="create-step-footer">
        <BigButton color="green" onClick={() => void save()} disabled={saving}>
          {saving ? 'ほぞんちゅう…' : 'かんせい!'}
        </BigButton>
      </div>
    </div>
  );
}
