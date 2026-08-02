/**
 * 精のせりふ音声(Blob)の再生。
 *
 * 一次経路: 共有AudioContext(audioUnlock.tsで解錠済み)でデコード再生。
 *   HTMLAudioElementはiOS Safariでユーザージェスチャー外のplay()が不規則に
 *   拒否されるため、WebAudioを優先する。
 * 二次経路: WebAudioが失敗したら new Audio()(再生画面で実績のある方式)。
 * それも失敗したら呼び出し側がWeb Speech TTSにフォールバックする。
 *
 * 【重要】失敗は必ず console.error に出す。サイレントに握りつぶすと
 * 「無音になる」だけで原因が追えなくなる(実際にそれで調査が難航した)。
 *
 * iOS Safariの注意点:
 * - 録音(getUserMedia)後にAudioContextが suspended / interrupted に戻ることが
 *   あるため、再生前に毎回 resume() を試みる。ただし resume() が解決しない
 *   ことがあるためタイムアウトを付け、動かないままなら即フォールバックする
 *   (awaitしっぱなしだと無音のままPromiseも解決せず、進行が止まる)。
 * - decodeAudioData はPromise形式が不安定な環境があるため、
 *   コールバック形式と両対応で呼ぶ。
 */
import { getAudioContext } from './audioUnlock';

let currentSource: AudioBufferSourceNode | null = null;
let currentAudio: HTMLAudioElement | null = null;
let currentUrl: string | null = null;

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
  if (currentAudio) {
    currentAudio.onended = null;
    currentAudio.onerror = null;
    currentAudio.pause();
    currentAudio = null;
  }
  if (currentUrl) {
    URL.revokeObjectURL(currentUrl);
    currentUrl = null;
  }
}

/** resume() が返ってこない環境があるため、タイムアウト付きで試す */
async function resumeWithTimeout(ctx: AudioContext, ms: number): Promise<void> {
  await Promise.race([
    ctx.resume().catch((err) => {
      console.error('[audio] AudioContext.resume() failed:', err);
    }),
    new Promise<void>((r) => setTimeout(r, ms)),
  ]);
}

/** Promise形式・コールバック形式の両対応で decodeAudioData を呼ぶ */
function decodeCompat(ctx: AudioContext, data: ArrayBuffer): Promise<AudioBuffer> {
  return new Promise((resolve, reject) => {
    const maybePromise = ctx.decodeAudioData(
      data,
      (buf) => resolve(buf),
      (err) => reject(err ?? new Error('decodeAudioData failed')),
    );
    // 新しい実装はPromiseも返す(どちらが先に確定しても1回しか効かない)
    if (maybePromise && typeof maybePromise.then === 'function') {
      maybePromise.then(resolve, reject);
    }
  });
}

/** 一次経路: WebAudioで再生(終了で解決。失敗はthrow) */
async function playViaWebAudio(blob: Blob): Promise<void> {
  const ctx = getAudioContext();
  if (ctx.state !== 'running') {
    await resumeWithTimeout(ctx, 800);
    // resume()で状態が変わりうるため再取得(TSの絞り込み回避のためキャスト)
    const state = ctx.state as AudioContextState;
    if (state !== 'running') {
      throw new Error(`AudioContext not running (state=${state})`);
    }
  }
  const buffer = await decodeCompat(ctx, await blob.arrayBuffer());
  stopAudioPlayback();
  return new Promise((resolve) => {
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    currentSource = source;
    const finish = () => {
      if (currentSource === source) currentSource = null;
      resolve();
    };
    source.onended = finish;
    source.start();
    // onendedが発火しない環境でも進行が止まらないよう保険のタイマー
    setTimeout(finish, buffer.duration * 1000 + 1500);
  });
}

/** 二次経路: HTMLAudio(再生画面 usePagePlayer と同じ実績ある方式) */
function playViaHtmlAudio(blob: Blob): Promise<void> {
  return new Promise((resolve, reject) => {
    stopAudioPlayback();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    currentAudio = audio;
    currentUrl = url;
    const finish = () => {
      if (currentAudio === audio) {
        currentAudio = null;
        currentUrl = null;
      }
      URL.revokeObjectURL(url);
      resolve();
    };
    audio.onended = finish;
    audio.onerror = () => {
      URL.revokeObjectURL(url);
      reject(audio.error ?? new Error('HTMLAudio playback error'));
    };
    audio.play().catch((err) => {
      URL.revokeObjectURL(url);
      reject(err);
    });
  });
}

/**
 * Blob音声(WAV/M4A等)を再生し、再生終了で解決する。
 * WebAudio → HTMLAudio の二段構え。両方失敗したらrejectする
 * (呼び出し側でWeb Speech TTS等にフォールバックすること)。
 */
export async function playAudioBlob(blob: Blob): Promise<void> {
  try {
    await playViaWebAudio(blob);
  } catch (err) {
    console.error('[audio] WebAudio playback failed, falling back to HTMLAudio:', err);
    try {
      await playViaHtmlAudio(blob);
    } catch (err2) {
      console.error('[audio] HTMLAudio playback also failed:', err2);
      throw err2;
    }
  }
}
