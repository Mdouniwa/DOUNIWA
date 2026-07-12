import { useCallback, useRef } from 'react';

/**
 * 連打対策のデバウンス(先頭のタップだけ通し、interval中は無視する)。
 * ページ送りボタンで使用(350ms)。
 */
export function useDebouncedTap<Args extends unknown[]>(
  fn: (...args: Args) => void,
  interval = 350,
): (...args: Args) => void {
  const lastRef = useRef(0);
  return useCallback(
    (...args: Args) => {
      const now = Date.now();
      if (now - lastRef.current < interval) return;
      lastRef.current = now;
      fn(...args);
    },
    [fn, interval],
  );
}
