import { BigButton } from '../../components/BigButton';

const CONFETTI_COLORS = ['#ffb300', '#42a5f5', '#66bb6a', '#ef5350', '#ab47bc', '#ffd54f'];
const CONFETTI_COUNT = 40;

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
      <div className="done-emoji" aria-hidden>
        🎉
      </div>
      <h2 className="done-title">えほんが できたよ!</h2>
      <BigButton color="primary" onClick={onHome}>
        ホームへ
      </BigButton>
    </div>
  );
}
