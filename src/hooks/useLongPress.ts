import { useCallback, useRef } from 'react';

/**
 * 長押し検出(親モード入口の3秒長押しに使用)。
 * 返り値のハンドラを要素に展開する。
 */
export function useLongPress(onLongPress: () => void, ms = 3000) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const start = useCallback(() => {
    timerRef.current = setTimeout(onLongPress, ms);
  }, [onLongPress, ms]);

  const cancel = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  return {
    onPointerDown: start,
    onPointerUp: cancel,
    onPointerLeave: cancel,
    onPointerCancel: cancel,
  };
}
