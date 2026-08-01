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
        // 未設定(旧経路)は録音があれば録音扱い、無ければ生成扱いにしておく
        narrationSource: p.narrationSource ?? (p.audioBlob ? 'recorded' : 'generated'),
      }));

      // 主人公の基準画像は pageIds に含めないPageとして保存する
      // (再生対象にはならないが、bookIdで紐づくため絵本削除時に一緒に消える)
      let characterRefImageId: string | undefined;
      if (draft.characterRef) {
        characterRefImageId = crypto.randomUUID();
        pages.push({
          id: characterRefImageId,
          bookId,
          imageBlob: draft.characterRef.imageBlob,
          thumbBlob: draft.characterRef.thumbBlob,
          captionText: '',
          audioBlob: null,
          audioMime: null,
          soundEffect: null,
          narrationSource: 'generated',
        });
      }

      const book: Book = {
        id: bookId,
        title: draft.title.trim() || THEME_LABELS[draft.theme],
        coverImageId: coverPageId,
        theme: draft.theme,
        pageIds: draft.pages.map((p) => p.id),
        createdAt: now,
        updatedAt: now,
        lastOpenedAt: now,
        conversation: draft.conversation,
        characterRefImageId,
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

      <p className="create-step-hint">ひょうしの えを えらんでね</p>
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
        <BigButton color="green" silent onClick={() => void save()} disabled={saving}>
          {saving ? 'ほぞんちゅう…' : 'かんせい!'}
        </BigButton>
      </div>
    </div>
  );
}
