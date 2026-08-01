/**
 * Gemini TTS による音声合成。
 * 精のせりふをやさしい声で読み上げたWAV(base64)を返す。
 * 失敗しても致命的ではない(クライアントがWeb Speech TTSにフォールバックする)ので null を返す。
 */
import { getAI, firstInlineData } from './genai.js';
import { pcmToWavBase64, sampleRateFromMime } from './audio.js';
import { config } from './env.js';

export async function synthesizeSpeech(
  text: string,
): Promise<{ base64: string; mime: string } | null> {
  try {
    const resp = await getAI().models.generateContent({
      model: config.ttsModel,
      // Gemini TTSは文頭の自然言語指示で話し方を制御できる(指示部分は読み上げられない)
      contents: `ちいさな子どもに やさしく ゆっくり、うれしそうに はなしかける こえで いってください: ${text}`,
      config: {
        responseModalities: ['AUDIO'],
        speechConfig: {
          voiceConfig: { prebuiltVoiceConfig: { voiceName: config.ttsVoice } },
        },
      },
    });
    const audio = firstInlineData(resp);
    if (!audio) return null;
    const rate = sampleRateFromMime(audio.mimeType);
    return { base64: pcmToWavBase64(audio.data, rate), mime: 'audio/wav' };
  } catch (err) {
    console.warn('[tts] failed:', err instanceof Error ? err.message : err);
    return null;
  }
}
