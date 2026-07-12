import { useCallback, useEffect, useRef, useState } from 'react';

export type RecorderState = 'idle' | 'recording' | 'error';

export interface RecordingResult {
  blob: Blob;
  mime: string;
}

/** iOS Safariはaudio/mp4のみ対応。他ブラウザはwebmにフォールバック */
function pickMimeType(): string | null {
  const candidates = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm'];
  for (const mime of candidates) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(mime)) {
      return mime;
    }
  }
  return null;
}

/**
 * ページ録音用フック。
 * start()→stop()で1回分のRecordingResultを返す。録り直しはstart()し直すだけ。
 */
export function useRecorder() {
  const [state, setState] = useState<RecorderState>('idle');
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  const cleanupStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    recorderRef.current = null;
  }, []);

  // アンマウント時にマイクを確実に解放
  useEffect(() => cleanupStream, [cleanupStream]);

  const start = useCallback(async (): Promise<boolean> => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = pickMimeType();
      const recorder = mime
        ? new MediaRecorder(stream, { mimeType: mime })
        : new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      streamRef.current = stream;
      recorderRef.current = recorder;
      recorder.start();
      setState('recording');
      return true;
    } catch {
      cleanupStream();
      setState('error');
      return false;
    }
  }, [cleanupStream]);

  const stop = useCallback((): Promise<RecordingResult | null> => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === 'inactive') {
      setState('idle');
      return Promise.resolve(null);
    }
    return new Promise((resolve) => {
      recorder.onstop = () => {
        const mime = recorder.mimeType || 'audio/mp4';
        const blob = new Blob(chunksRef.current, { type: mime });
        cleanupStream();
        setState('idle');
        resolve(blob.size > 0 ? { blob, mime } : null);
      };
      recorder.stop();
    });
  }, [cleanupStream]);

  /** 録音を破棄して止める(保存しない) */
  const cancel = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = null;
      recorder.stop();
    }
    cleanupStream();
    setState('idle');
  }, [cleanupStream]);

  return { state, start, stop, cancel };
}
