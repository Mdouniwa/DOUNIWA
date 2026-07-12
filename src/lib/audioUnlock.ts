/**
 * iOS Safariの自動再生制限対策。
 * 初回のユーザータップで共有AudioContextをresumeし、
 * 無音バッファを1つ再生してアンロックする定番処理。
 * あわせてspeechSynthesisも空発話でウォームアップする。
 */

let sharedContext: AudioContext | null = null;
let unlocked = false;

/** アプリ全体で共有するAudioContext(効果音・録音プレビューで使用) */
export function getAudioContext(): AudioContext {
  if (!sharedContext) {
    sharedContext = new AudioContext();
  }
  return sharedContext;
}

export function isAudioUnlocked(): boolean {
  return unlocked;
}

/**
 * ユーザージェスチャー内から呼ぶこと。
 * App.tsxで初回pointerdownに仕込む。複数回呼んでも安全。
 */
export async function unlockAudio(): Promise<void> {
  const ctx = getAudioContext();
  try {
    if (ctx.state === 'suspended') {
      await ctx.resume();
    }
    if (!unlocked) {
      // 無音バッファ再生でiOSの再生許可を得る
      const buffer = ctx.createBuffer(1, 1, 22050);
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      source.start(0);

      // speechSynthesisもユーザージェスチャー内で一度動かしておく
      if ('speechSynthesis' in window) {
        const utterance = new SpeechSynthesisUtterance('');
        utterance.volume = 0;
        window.speechSynthesis.speak(utterance);
      }
      unlocked = true;
    }
  } catch {
    // 失敗しても次のタップで再試行される
    unlocked = false;
  }
}
