/**
 * 固定セリフの音声を事前生成する開発時スクリプト。
 * 1問目(FIRST_QUESTION)はクライアント固定でサーバーを呼ばないため、
 * 読み上げ音声も静的ファイルとして同梱する(待ち時間ゼロ+ランタイムコストゼロ)。
 *
 * 実行方法:
 *   node --env-file="$HOME/.ehon-art.env" scripts/generate-voice.mjs
 *
 * 出力: public/audio/first-question.m4a(afconvertが無い環境では .wav)
 * 声・話し方は server/src/env.ts の既定(Sulafat/わかいおねえさん)と揃えること。
 */
import { GoogleGenAI } from '@google/genai';
import { execFileSync } from 'node:child_process';
import { mkdir, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT_DIR = path.join(ROOT, 'public', 'audio');

const TTS_MODEL = process.env.TTS_MODEL || 'gemini-3.1-flash-tts-preview';
const TTS_VOICE = process.env.TTS_VOICE || 'Sulafat';
const TTS_STYLE =
  process.env.TTS_STYLE ||
  'わかい おねえさんが、やさしく すんだ こえで、あたたかく はなしかけるように いってください';

// src/lib/talkApi.ts の FIRST_QUESTION と一致させること
const LINES = [
  [
    'first-question',
    'こんにちは! いっしょに えほんを つくろう! さいしょに、おはなしの しゅやくは だれに する?',
  ],
];

if (!process.env.GEMINI_API_KEY) {
  console.error('GEMINI_API_KEY を設定してください');
  process.exit(1);
}

/** GeminiのPCM(16bit LE)にWAVヘッダを付ける */
function pcmToWav(pcm, sampleRate) {
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + pcm.length, 4);
  header.write('WAVE', 8);
  header.write('fmt ', 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(1, 22); // mono
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(sampleRate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36);
  header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]);
}

const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
await mkdir(OUT_DIR, { recursive: true });

for (const [name, text] of LINES) {
  console.log(`生成中 (${name}) voice=${TTS_VOICE}...`);
  const resp = await ai.models.generateContent({
    model: TTS_MODEL,
    contents: `${TTS_STYLE}: ${text}`,
    config: {
      responseModalities: ['AUDIO'],
      speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: TTS_VOICE } } },
    },
  });
  const parts = resp.candidates?.[0]?.content?.parts ?? [];
  const audio = parts.find((p) => p.inlineData?.data)?.inlineData;
  if (!audio) throw new Error('音声が返りませんでした');
  const rate = Number(/rate=(\d+)/.exec(audio.mimeType ?? '')?.[1] ?? 24000);
  const wavPath = path.join(OUT_DIR, `${name}.wav`);
  await writeFile(wavPath, pcmToWav(Buffer.from(audio.data, 'base64'), rate));

  // macOSなら afconvert でAAC(m4a)に圧縮(precache肥大を防ぐ)
  try {
    const m4aPath = path.join(OUT_DIR, `${name}.m4a`);
    execFileSync('afconvert', ['-f', 'm4af', '-d', 'aac', '-b', '64000', wavPath, m4aPath]);
    await rm(wavPath);
    console.log(`✓ ${m4aPath}`);
  } catch {
    console.log(`✓ ${wavPath}(afconvertが無いためWAVのまま。クライアントのパスも合わせること)`);
  }
}
