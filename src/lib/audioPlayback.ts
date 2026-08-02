/**
 * 共有AudioContext(audioUnlock.tsで解錠済み)によるBlob音声再生。
 *
 * HTMLAudioElement(new Audio())はiOS Safariでユーザージェスチャー外の
 * play() が拒否されることがあり、マイク録音と交互に使うと再生が不規則に
 * 失敗する(鳴ったり鳴らなかったりする)。WebAudioなら初回解錠後は
 * プログラムからの再生が安定するため、精のせりふ再生はこちらを使う。
 *
 * 注意: iOSは録音(getUserMedia)のオーディオセッション切替後に
 * AudioContextが suspended / interrupted に戻ることがあるため、
 * 再生前に毎回 resume() を試みる。
 */
import { getAudioContext } from './audioUnlock';

let currentSource: AudioBufferSourceNode | null = null;

/** 再生中の音声を止める(再生していなければ何もしない) */
export function stopAudioPlayback(): void {
  const source = currentSource;
  currentSource = null;
  if (source) {
    try {
      source.onended = null;
      source.stop();
    } catch {
      // 既に停止済みなら無視
    }
  }
}

/**
 * Blob音声(WAV等)をデコードして再生し、再生終了で解決する。
 * デコード失敗・再生不能時はrejectする(呼び出し側でTTS等にフォールバック)。
 */
export async function playAudioBlob(blob: Blob): Promise<void> {
  const ctx = getAudioContext();
  if (ctx.state !== 'running') {
    // 録音セッション後のsuspended/interruptedからの復帰
    await ctx.resume().catch(() => {});
  }
  const buffer = await ctx.decodeAudioData(await blob.arrayBuffer());
  stopAudioPlayback();
  return new Promise((resolve) => {
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    currentSource = source;
    source.onended = () => {
      if (currentSource === source) currentSource = null;
      resolve();
    };
    source.start();
  });
}
