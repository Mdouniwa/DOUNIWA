import { useCallback, useEffect, useRef, useState } from 'react';
import type { Page, Settings } from '../types';
import { cancelSpeech, speak } from '../lib/tts';

export type NarrationState = 'idle' | 'playingGenerated' | 'playingRecorded' | 'playingTts';

/**
 * 再生画面のナレーション状態機械。
 * ページが変わるたびに「全停止 → フォールバック解決 → 再生」を一本化する。
 * 再生の優先順位:
 *   1. 音声Blobあり(AI生成 or 子どもの録音) → その音声を再生
 *      (narrationSource で generated / recorded を区別。どちらも audioBlob をそのまま使う)
 *   2. 音声が無く captionText あり → ローカルWeb Speech APIでTTS読み上げ(最終フォールバック)
 *   3. どちらも無ければ無音
 * settings.narrationMode === 'tts' の場合は、音声Blobがあっても常にローカルTTSを使う。
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

    // captionText があればローカルTTSで読み上げ、無ければ無音で終了
    const speakCaption = () => {
      if (sessionRef.current !== session) return;
      if (page.captionText.trim()) {
        setState('playingTts');
        void speak(page.captionText).then(done);
      } else {
        done();
      }
    };

    const useAudioBlob = page.audioBlob && settings.narrationMode !== 'tts';

    if (useAudioBlob && page.audioBlob) {
      const url = URL.createObjectURL(page.audioBlob);
      urlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      setState(page.narrationSource === 'recorded' ? 'playingRecorded' : 'playingGenerated');
      audio.onended = done;
      // 生成音声の再生に失敗したときは captionText のTTSにフォールバック
      audio.onerror = speakCaption;
      audio.play().catch(speakCaption);
    } else {
      speakCaption();
    }

    return stopAll;
  }, [page, settings, stopAll]);

  return { state, stopAll };
}
