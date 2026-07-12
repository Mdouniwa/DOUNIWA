import { useCallback, useEffect, useRef, useState } from 'react';
import type { Page, Settings } from '../types';
import { cancelSpeech, speak } from '../lib/tts';

export type NarrationState = 'idle' | 'playingRecorded' | 'playingTts';

/**
 * 再生画面のナレーション状態機械。
 * ページが変わるたびに「全停止 → フォールバック解決 → 再生」を一本化する。
 *   録音あり(narrationMode=recorded) → 録音再生
 *   なければ captionText → TTS読み上げ
 *   どちらもなければ無音
 */
export function usePagePlayer(page: Page | null, settings: Settings | null) {
  const [state, setState] = useState<NarrationState>('idle');
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  // ページ切替後に前ページの完了コールバックが状態を触らないよう世代番号で守る
  const sessionRef = useRef(0);

  const stopAll = useCallback(() => {
    sessionRef.current++;
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    cancelSpeech();
    setState('idle');
  }, []);

  useEffect(() => {
    stopAll();
    if (!page || !settings || !settings.autoPlayOn) return;

    const session = sessionRef.current;
    const done = () => {
      if (sessionRef.current === session) setState('idle');
    };

    if (page.audioBlob && settings.narrationMode === 'recorded') {
      const url = URL.createObjectURL(page.audioBlob);
      urlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      setState('playingRecorded');
      audio.onended = done;
      audio.onerror = done;
      audio.play().catch(done);
    } else if (page.captionText.trim()) {
      setState('playingTts');
      void speak(page.captionText).then(done);
    }

    return stopAll;
  }, [page, settings, stopAll]);

  return { state, stopAll };
}
