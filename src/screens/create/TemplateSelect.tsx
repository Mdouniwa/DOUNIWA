import type { Theme } from '../../types';
import { THEME_EMOJI, THEME_LABELS } from '../../types';
import { playSound } from '../../lib/soundEffects';

const THEMES: Theme[] = ['odekake', 'birthday', 'animal', 'vehicle'];

interface TemplateSelectProps {
  theme: Theme;
  onSelect: (theme: Theme) => void;
}

/** Step1: テンプレ(テーマ)選択 */
export function TemplateSelect({ theme, onSelect }: TemplateSelectProps) {
  return (
    <div className="create-step">
      <h2 className="create-step-title">どんな えほんに する?</h2>
      <div className="template-grid">
        {THEMES.map((t) => (
          <button
            key={t}
            className={`template-card pressable ${t === theme ? 'template-card--selected' : ''}`}
            onClick={() => {
              playSound('tap');
              onSelect(t);
            }}
          >
            <span className="template-emoji" aria-hidden>
              {THEME_EMOJI[t]}
            </span>
            <span className="template-label">{THEME_LABELS[t]}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
