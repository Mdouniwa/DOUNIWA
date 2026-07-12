import { useRef, useState } from 'react';
import type { DraftPage } from './draft';
import { MAX_PHOTOS, MIN_PHOTOS } from './draft';
import { resizeImage } from '../../lib/imageResize';
import { BigButton } from '../../components/BigButton';
import { PageThumb } from './PageThumb';

interface PhotoPickProps {
  pages: DraftPage[];
  onChange: (pages: DraftPage[]) => void;
  onNext: () => void;
}

/** Step2: 写真選択(5〜10枚、Canvasリサイズしてから保持) */
export function PhotoPick({ pages, onChange, onNext }: PhotoPickProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setBusy(true);
    try {
      const room = MAX_PHOTOS - pages.length;
      const picked = Array.from(files).slice(0, room);
      const added: DraftPage[] = [];
      for (const file of picked) {
        try {
          const { imageBlob, thumbBlob } = await resizeImage(file);
          added.push({
            id: crypto.randomUUID(),
            imageBlob,
            thumbBlob,
            captionText: '',
            audioBlob: null,
            audioMime: null,
            soundEffect: null,
          });
        } catch {
          // 読めない写真(HEIC等の失敗)はスキップして続行
        }
      }
      onChange([...pages, ...added]);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const removePage = (id: string) => onChange(pages.filter((p) => p.id !== id));

  const canNext = pages.length >= MIN_PHOTOS && pages.length <= MAX_PHOTOS;

  return (
    <div className="create-step">
      <h2 className="create-step-title">しゃしんを えらぼう</h2>
      <p className="create-step-hint">
        {MIN_PHOTOS}まい から {MAX_PHOTOS}まい まで(いま {pages.length}まい)
      </p>

      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={(e) => void handleFiles(e.target.files)}
      />

      <div className="photo-grid">
        {pages.map((p) => (
          <div key={p.id} className="photo-cell">
            <PageThumb blob={p.thumbBlob} />
            <button
              className="photo-remove pressable"
              aria-label="この写真を外す"
              onClick={() => removePage(p.id)}
            >
              ✕
            </button>
          </div>
        ))}
        {pages.length < MAX_PHOTOS && (
          <button
            className="photo-add pressable"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
          >
            {busy ? '…' : '＋'}
          </button>
        )}
      </div>

      <div className="create-step-footer">
        <BigButton onClick={onNext} disabled={!canNext || busy} color="green">
          つぎへ →
        </BigButton>
      </div>
    </div>
  );
}
