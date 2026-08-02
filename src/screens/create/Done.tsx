import { BigButton } from '../../components/BigButton';
import { DecoSprinkles, type DecoItem } from '../../components/DecoSprinkles';
import { FAIRY_IMAGES } from '../../lib/artAssets';

const CONFETTI_COLORS = ['#ffb300', '#42a5f5', '#66bb6a', '#ef5350', '#ab47bc', '#ffd54f'];
const CONFETTI_COUNT = 40;

/** お祝いに駆けつける動物たち */
const DONE_DECO: DecoItem[] = [
  { name: 'rabbit', style: { bottom: '14%', left: '4%', width: '80px', transform: 'rotate(-6deg)' } },
  { name: 'bear', style: { bottom: '13%', right: '4%', width: '84px', transform: 'rotate(6deg)' } },
  { name: 'star', style: { top: '10%', left: '8%', width: '56px', transform: 'rotate(-12deg)' }, tier: 2 },
  { name: 'balloon', style: { top: '8%', right: '6%', width: '72px', transform: 'rotate(8deg)' }, tier: 2 },
];

/** Step6: 保存完了のお祝い(紙吹雪アニメ)→ ホームへ */
export function Done({ onHome }: { onHome: () => void }) {
  return (
    <div className="create-step done-step">
      <div className="confetti" aria-hidden>
        {Array.from({ length: CONFETTI_COUNT }, (_, i) => (
          <span
            key={i}
            className="confetti-piece"
            style={{
              left: `${(i * 97) % 100}%`,
              background: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
              animationDelay: `${(i % 10) * 0.18}s`,
              animationDuration: `${2.4 + (i % 5) * 0.35}s`,
            }}
          />
        ))}
      </div>
      <DecoSprinkles items={DONE_DECO} />
      <img className="done-fairy" src={FAIRY_IMAGES.cheer} alt="えほんの精" draggable={false} />
      <h2 className="done-title">えほんが できたよ!</h2>
      <BigButton color="primary" onClick={onHome}>
        ホームへ
      </BigButton>
    </div>
  );
}
