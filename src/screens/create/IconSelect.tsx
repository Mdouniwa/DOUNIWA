import { ICON_POOL, iconEmoji } from '../../lib/icons';
import { ICON_COUNT } from '../../lib/generateApi';
import { playSound } from '../../lib/soundEffects';
import { BigButton } from '../../components/BigButton';
import './iconSelect.css';

interface IconSelectProps {
  /** 選択済みキーワード(選択順を保持) */
  selected: string[];
  onChange: (selected: string[]) => void;
  onNext: () => void;
}

/** Step1: アイコンを選ぶ(タップ順に5個まで、再タップで解除、←→で並び替え) */
export function IconSelect({ selected, onChange, onNext }: IconSelectProps) {
  const toggle = (keyword: string) => {
    playSound('tap');
    if (selected.includes(keyword)) {
      onChange(selected.filter((k) => k !== keyword));
    } else if (selected.length < ICON_COUNT) {
      onChange([...selected, keyword]);
    }
  };

  const move = (index: number, delta: -1 | 1) => {
    const target = index + delta;
    if (target < 0 || target >= selected.length) return;
    playSound('tap');
    const next = [...selected];
    const [k] = next.splice(index, 1);
    next.splice(target, 0, k);
    onChange(next);
  };

  const remove = (keyword: string) => {
    playSound('tap');
    onChange(selected.filter((k) => k !== keyword));
  };

  const full = selected.length === ICON_COUNT;

  return (
    <div className="create-step icon-step">
      <h2 className="create-step-title">すきな えを 5つ えらぼう</h2>
      <p className="create-step-hint">
        えらんだ じゅんに おはなしに なるよ(いま {selected.length} / {ICON_COUNT})
      </p>

      {/* 選択済みスロット(順序表示・並び替え・解除) */}
      <div className="icon-slots">
        {Array.from({ length: ICON_COUNT }, (_, i) => {
          const keyword = selected[i];
          if (!keyword) {
            return (
              <div key={i} className="icon-slot icon-slot--empty">
                <span className="icon-slot-num">{i + 1}</span>
              </div>
            );
          }
          return (
            <div key={i} className="icon-slot">
              <span className="icon-slot-num">{i + 1}</span>
              <button
                className="icon-slot-emoji pressable"
                onClick={() => remove(keyword)}
                aria-label={`${keyword}をはずす`}
              >
                {iconEmoji(keyword)}
              </button>
              <div className="icon-slot-move">
                <button
                  className="icon-move pressable"
                  disabled={i === 0}
                  onClick={() => move(i, -1)}
                  aria-label="まえへ"
                >
                  ←
                </button>
                <button
                  className="icon-move pressable"
                  disabled={i === selected.length - 1}
                  onClick={() => move(i, 1)}
                  aria-label="うしろへ"
                >
                  →
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* アイコンプール */}
      <div className="icon-grid">
        {ICON_POOL.map((icon) => {
          const order = selected.indexOf(icon.keyword);
          const isSelected = order >= 0;
          return (
            <button
              key={icon.keyword}
              className={`icon-cell pressable ${isSelected ? 'icon-cell--selected' : ''}`}
              onClick={() => toggle(icon.keyword)}
              disabled={!isSelected && full}
            >
              <span className="icon-cell-emoji" aria-hidden>
                {icon.emoji}
              </span>
              <span className="icon-cell-label">{icon.keyword}</span>
              {isSelected && <span className="icon-cell-badge">{order + 1}</span>}
            </button>
          );
        })}
      </div>

      <div className="create-step-footer">
        <BigButton color="green" silent onClick={onNext} disabled={!full}>
          えほんを つくる →
        </BigButton>
      </div>
    </div>
  );
}
