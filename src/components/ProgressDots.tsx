import './ProgressDots.css';

interface ProgressDotsProps {
  total: number;
  current: number; // 0-indexed
}

/** 作成フローの進捗ドット表示 */
export function ProgressDots({ total, current }: ProgressDotsProps) {
  return (
    <div className="progress-dots" role="progressbar" aria-valuenow={current + 1} aria-valuemax={total}>
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={`progress-dot ${i <= current ? 'progress-dot--done' : ''} ${i === current ? 'progress-dot--current' : ''}`}
        />
      ))}
    </div>
  );
}
