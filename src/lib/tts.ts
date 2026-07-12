/**
 * Web Speech API (speechSynthesis) による日本語読み上げ。
 * 録音がないページのキャプション読み上げフォールバックに使う。
 */

let cachedVoice: SpeechSynthesisVoice | null = null;

function pickJapaneseVoice(): SpeechSynthesisVoice | null {
  if (cachedVoice) return cachedVoice;
  const voices = window.speechSynthesis?.getVoices() ?? [];
  // ja-JPを優先、なければja*
  cachedVoice =
    voices.find((v) => v.lang === 'ja-JP') ??
    voices.find((v) => v.lang.startsWith('ja')) ??
    null;
  return cachedVoice;
}

// iOS/Safariでは音声リストが非同期に届くため先読みしておく
if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
  window.speechSynthesis.addEventListener?.('voiceschanged', () => {
    cachedVoice = null;
    pickJapaneseVoice();
  });
  pickJapaneseVoice();
}

export function isTtsAvailable(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

/**
 * テキストを読み上げる。終了(またはキャンセル・エラー)で解決するPromiseを返す。
 */
export function speak(text: string): Promise<void> {
  if (!isTtsAvailable() || !text.trim()) return Promise.resolve();
  return new Promise((resolve) => {
    // 前の発話が残っていると詰まるため必ずリセット
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'ja-JP';
    const voice = pickJapaneseVoice();
    if (voice) utterance.voice = voice;
    utterance.rate = 0.95; // 子ども向けに少しゆっくり
    utterance.onend = () => resolve();
    utterance.onerror = () => resolve();
    window.speechSynthesis.speak(utterance);
  });
}

export function cancelSpeech(): void {
  if (isTtsAvailable()) {
    window.speechSynthesis.cancel();
  }
}
