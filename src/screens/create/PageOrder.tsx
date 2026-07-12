import type { DraftPage } from './draft';
import { BigButton } from '../../components/BigButton';
import { PageThumb } from './PageThumb';

interface PageOrderProps {
  pages: DraftPage[];
  onChange: (pages: DraftPage[]) => void;
  onNext: () => void;
}

/** Step3: ページ順の確認・入れ替え(←→ボタン方式、ドラッグなし) */
export function PageOrder({ pages, onChange, onNext }: PageOrderProps) {
  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= pages.length) return;
    const next = [...pages];
    const [item] = next.splice(index, 1);
    next.splice(target, 0, item);
    onChange(next);
  };

  return (
    <div className="create-step">
      <h2 className="create-step-title">ページの じゅんばん</h2>
      <p className="create-step-hint">← → で いれかえられるよ</p>

      <div className="order-grid">
        {pages.map((p, i) => (
          <div key={p.id} className="order-cell">
            <span className="order-number">{i + 1}</span>
            <PageThumb blob={p.thumbBlob} />
            <div className="order-buttons">
              <button
                className="order-move pressable"
                aria-label="まえへ"
                disabled={i === 0}
                onClick={() => move(i, -1)}
              >
                ←
              </button>
              <button
                className="order-move pressable"
                aria-label="うしろへ"
                disabled={i === pages.length - 1}
                onClick={() => move(i, 1)}
              >
                →
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="create-step-footer">
        <BigButton onClick={onNext} color="green">
          つぎへ →
        </BigButton>
      </div>
    </div>
  );
}
