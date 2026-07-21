/**
 * 効果音のWebAudio合成(外部ファイル不使用)。
 * OfflineAudioContextで一度レンダリングしてAudioBufferをキャッシュし、
 * 再生時は共有AudioContextで即時再生する。
 *
 * 音質方針: ADSRエンベロープ + 複数オシレーターの重ね + 合成IRの
 * コンボリューションリバーブ/フィードバックディレイで安っぽさを避ける。
 */
import type { SynthSound } from '../types';
import { getAudioContext } from './audioUnlock';

const SAMPLE_RATE = 44100;

// ---------------------------------------------------------------- helpers

/** ADSRエンベロープをGainNodeのgainに書き込む */
function adsr(
  gain: AudioParam,
  t0: number,
  opts: { a: number; d: number; s: number; r: number; dur: number; peak?: number },
) {
  const peak = opts.peak ?? 1;
  gain.setValueAtTime(0.0001, t0);
  gain.exponentialRampToValueAtTime(peak, t0 + opts.a);
  gain.exponentialRampToValueAtTime(Math.max(peak * opts.s, 0.0001), t0 + opts.a + opts.d);
  gain.setValueAtTime(Math.max(peak * opts.s, 0.0001), t0 + opts.dur);
  gain.exponentialRampToValueAtTime(0.0001, t0 + opts.dur + opts.r);
}

/** ホワイトノイズのAudioBuffer */
function noiseBuffer(ctx: BaseAudioContext, seconds: number): AudioBuffer {
  const buf = ctx.createBuffer(1, Math.ceil(seconds * ctx.sampleRate), ctx.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
  return buf;
}

/** 指数減衰ノイズによる簡易インパルスレスポンス(リバーブ用) */
function impulseResponse(ctx: BaseAudioContext, seconds: number, decay: number): AudioBuffer {
  const len = Math.ceil(seconds * ctx.sampleRate);
  const buf = ctx.createBuffer(2, len, ctx.sampleRate);
  for (let ch = 0; ch < 2; ch++) {
    const data = buf.getChannelData(ch);
    for (let i = 0; i < len; i++) {
      data[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay);
    }
  }
  return buf;
}

interface FxBus {
  dry: GainNode;
  wet: GainNode;
  input: GainNode;
}

/** dry + コンボリューションリバーブのバスを作る */
function reverbBus(ctx: BaseAudioContext, wetLevel: number, irSeconds = 1.2, decay = 3): FxBus {
  const input = ctx.createGain();
  const dry = ctx.createGain();
  const wet = ctx.createGain();
  const convolver = ctx.createConvolver();
  convolver.buffer = impulseResponse(ctx, irSeconds, decay);
  dry.gain.value = 1;
  wet.gain.value = wetLevel;
  input.connect(dry);
  input.connect(convolver);
  convolver.connect(wet);
  dry.connect(ctx.destination);
  wet.connect(ctx.destination);
  return { input, dry, wet };
}

/** フィードバックディレイ(キラキラ用) */
function feedbackDelay(
  ctx: BaseAudioContext,
  input: AudioNode,
  output: AudioNode,
  time: number,
  feedback: number,
  level: number,
) {
  const delay = ctx.createDelay(1);
  delay.delayTime.value = time;
  const fb = ctx.createGain();
  fb.gain.value = feedback;
  const send = ctx.createGain();
  send.gain.value = level;
  input.connect(delay);
  delay.connect(fb);
  fb.connect(delay);
  delay.connect(send);
  send.connect(output);
}

// ------------------------------------------------------------- renderers

/**
 * 拍手: 実際の拍手が持つ「複数周波数帯にまたがる広帯域の衝撃音」を再現するため、
 * 中心周波数の異なる5本のバンドパスフィルターを並列にかけたノイズバーストを
 * 同時に鳴らして混ぜ合わせる(単一帯域のフィルターだけでは出せない、パチッという
 * 弾けるような質感になる)。複数人が微妙にタイミングをずらして叩いている重なりも維持。
 */
function renderClap(ctx: OfflineAudioContext) {
  const bus = reverbBus(ctx, 0.35, 0.9, 2.5);
  const noise = noiseBuffer(ctx, 0.09);
  // 低域(手のひらの「パン」感)〜高域(指先の「チッ」感)まで5帯域を並列合成
  const BANDS = [800, 1400, 2200, 3200, 4500];

  const clapAt = (t: number, loud: number) => {
    for (const freq of BANDS) {
      const src = ctx.createBufferSource();
      src.buffer = noise;
      const bp = ctx.createBiquadFilter();
      bp.type = 'bandpass';
      // 帯域ごとにわずかなゆらぎを持たせ、毎回微妙に違う音になるようにする
      bp.frequency.value = freq * (0.92 + Math.random() * 0.16);
      bp.Q.value = 2 + Math.random() * 1.5;
      const g = ctx.createGain();
      // アタックは3ms以下の急峻な立ち上がり(衝撃音らしさの核)
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(loud * (0.55 + Math.random() * 0.35), t + 0.0025);
      // 高域ほど短く減衰し、低域はわずかに尾を引く(生の拍手に近い質感)
      const decay = 0.04 + Math.random() * 0.02 + ((4500 - freq) / 4500) * 0.035;
      g.gain.exponentialRampToValueAtTime(0.0001, t + decay);
      src.connect(bp).connect(g).connect(bus.input);
      src.start(t);
    }
  };

  // 大勢の拍手: 0〜1.1秒にランダム配置(タイミングのずれた複数バーストの重なり)
  for (let i = 0; i < 22; i++) {
    clapAt(0.02 + Math.random() * 1.05, 0.22 + Math.random() * 0.3);
  }
  // 先頭にそろった「パン!」で立ち上がりをはっきりさせる
  clapAt(0.01, 0.7);
}

/** どうぶつ: 子犬の「ワン!ワン!」(ピッチが落ちるsaw+三角波、フォルマント風BP) */
function renderAnimal(ctx: OfflineAudioContext) {
  const bus = reverbBus(ctx, 0.2, 0.6, 3);
  const bark = (t: number) => {
    const dur = 0.18;
    const osc1 = ctx.createOscillator();
    osc1.type = 'sawtooth';
    const osc2 = ctx.createOscillator();
    osc2.type = 'triangle';
    // 立ち上がりで一気に上がって落ちるピッチ = 吠え声らしさ
    for (const [osc, mult] of [
      [osc1, 1],
      [osc2, 2],
    ] as const) {
      osc.frequency.setValueAtTime(320 * mult, t);
      osc.frequency.exponentialRampToValueAtTime(660 * mult, t + 0.03);
      osc.frequency.exponentialRampToValueAtTime(240 * mult, t + dur);
    }
    const formant = ctx.createBiquadFilter();
    formant.type = 'bandpass';
    formant.frequency.setValueAtTime(900, t);
    formant.frequency.exponentialRampToValueAtTime(500, t + dur);
    formant.Q.value = 1.5;
    const g = ctx.createGain();
    adsr(g.gain, t, { a: 0.015, d: 0.06, s: 0.4, r: 0.07, dur: dur - 0.05, peak: 0.5 });
    const g2 = ctx.createGain();
    g2.gain.value = 0.35;
    osc1.connect(formant);
    osc2.connect(g2).connect(formant);
    formant.connect(g).connect(bus.input);
    osc1.start(t);
    osc1.stop(t + dur + 0.1);
    osc2.start(t);
    osc2.stop(t + dur + 0.1);
  };
  bark(0.02);
  bark(0.32);
}

/** くるま: エンジン始動→ブロロロ(ピッチ上昇saw×2+サブ+ノイズ)+プップー */
function renderCar(ctx: OfflineAudioContext) {
  const bus = reverbBus(ctx, 0.18, 0.7, 3);

  // エンジン: デチューンしたsaw2本 + サイン(サブ) + 揺らぎLFO
  const engineGain = ctx.createGain();
  adsr(engineGain.gain, 0.02, { a: 0.08, d: 0.2, s: 0.8, r: 0.35, dur: 0.85, peak: 0.32 });
  const lp = ctx.createBiquadFilter();
  lp.type = 'lowpass';
  lp.frequency.setValueAtTime(400, 0);
  lp.frequency.exponentialRampToValueAtTime(1400, 1.0);
  engineGain.connect(lp).connect(bus.input);

  for (const detune of [-8, 6]) {
    const osc = ctx.createOscillator();
    osc.type = 'sawtooth';
    osc.detune.value = detune;
    osc.frequency.setValueAtTime(55, 0.02);
    osc.frequency.exponentialRampToValueAtTime(160, 1.1);
    osc.connect(engineGain);
    osc.start(0.02);
    osc.stop(1.3);
  }
  const sub = ctx.createOscillator();
  sub.type = 'sine';
  sub.frequency.setValueAtTime(28, 0.02);
  sub.frequency.exponentialRampToValueAtTime(80, 1.1);
  const subG = ctx.createGain();
  subG.gain.value = 0.5;
  sub.connect(subG).connect(engineGain);
  sub.start(0.02);
  sub.stop(1.3);

  // 回転の揺らぎ
  const lfo = ctx.createOscillator();
  lfo.frequency.value = 11;
  const lfoG = ctx.createGain();
  lfoG.gain.value = 0.06;
  lfo.connect(lfoG).connect(engineGain.gain);
  lfo.start(0);
  lfo.stop(1.3);

  // クラクション「プップー」(2和音の矩形波+BP)
  const honk = (t: number, dur: number) => {
    for (const f of [440, 554]) {
      const osc = ctx.createOscillator();
      osc.type = 'square';
      osc.frequency.value = f;
      const bp = ctx.createBiquadFilter();
      bp.type = 'bandpass';
      bp.frequency.value = 900;
      bp.Q.value = 0.8;
      const g = ctx.createGain();
      adsr(g.gain, t, { a: 0.02, d: 0.03, s: 0.85, r: 0.06, dur: dur - 0.05, peak: 0.22 });
      osc.connect(bp).connect(g).connect(bus.input);
      osc.start(t);
      osc.stop(t + dur + 0.15);
    }
  };
  honk(1.05, 0.16);
  honk(1.3, 0.3);
}

/** キラキラ: ベル(サイン+高次倍音)の上昇アルペジオ + ディレイの残響 */
function renderSparkle(ctx: OfflineAudioContext) {
  const bus = reverbBus(ctx, 0.45, 1.6, 2.2);
  feedbackDelay(ctx, bus.input, ctx.destination, 0.19, 0.35, 0.25);

  const bell = (t: number, freq: number, loud: number) => {
    // 基音 + 非整数倍音(ベルらしさ) + きらめきの高音
    const partials: Array<[number, number]> = [
      [1, 1],
      [2.76, 0.4],
      [5.4, 0.18],
    ];
    for (const [ratio, amp] of partials) {
      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.value = freq * ratio;
      const g = ctx.createGain();
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(loud * amp, t + 0.008);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.5 + ratio * 0.05);
      osc.connect(g).connect(bus.input);
      osc.start(t);
      osc.stop(t + 0.9);
    }
  };
  // ペンタトニックの上昇 + 最後に高いオクターブ
  const notes = [880, 987, 1174, 1318, 1568, 1760];
  notes.forEach((f, i) => bell(0.02 + i * 0.09, f, 0.3));
  bell(0.62, 2093, 0.35);
  bell(0.72, 2637, 0.25);
}

/** ラッパ: 倍音を重ねたブラス風「パパパーン!」ファンファーレ */
function renderTrumpet(ctx: OfflineAudioContext) {
  const bus = reverbBus(ctx, 0.3, 1.1, 2.6);

  const brass = (t: number, freq: number, dur: number, loud: number) => {
    const g = ctx.createGain();
    adsr(g.gain, t, { a: 0.03, d: 0.08, s: 0.7, r: 0.12, dur: dur - 0.08, peak: loud });
    // ブラスらしい明るさ: ローパスを立ち上がりで開く
    const lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.setValueAtTime(freq * 2, t);
    lp.frequency.exponentialRampToValueAtTime(freq * 7, t + 0.06);
    lp.Q.value = 1;
    g.connect(lp).connect(bus.input);

    // saw主体 + 1オクターブ上を薄く + ビブラート
    const osc1 = ctx.createOscillator();
    osc1.type = 'sawtooth';
    osc1.frequency.value = freq;
    const osc2 = ctx.createOscillator();
    osc2.type = 'sawtooth';
    osc2.frequency.value = freq * 2.003;
    const g2 = ctx.createGain();
    g2.gain.value = 0.25;
    const vib = ctx.createOscillator();
    vib.frequency.value = 6;
    const vibG = ctx.createGain();
    vibG.gain.value = freq * 0.008;
    vib.connect(vibG);
    vibG.connect(osc1.frequency);
    osc1.connect(g);
    osc2.connect(g2).connect(g);
    for (const o of [osc1, osc2, vib]) {
      o.start(t);
      o.stop(t + dur + 0.2);
    }
  };
  // ド ド ド ソ! (C5, G5)
  brass(0.02, 523.25, 0.16, 0.4);
  brass(0.24, 523.25, 0.16, 0.4);
  brass(0.46, 523.25, 0.16, 0.42);
  brass(0.68, 783.99, 0.75, 0.5);
}

/** UIタップ音: 丸みのある短いポップ */
function renderTap(ctx: OfflineAudioContext) {
  const osc = ctx.createOscillator();
  osc.type = 'sine';
  osc.frequency.setValueAtTime(880, 0);
  osc.frequency.exponentialRampToValueAtTime(440, 0.09);
  const osc2 = ctx.createOscillator();
  osc2.type = 'triangle';
  osc2.frequency.setValueAtTime(1760, 0);
  osc2.frequency.exponentialRampToValueAtTime(880, 0.09);
  const g = ctx.createGain();
  g.gain.setValueAtTime(0.0001, 0);
  g.gain.exponentialRampToValueAtTime(0.3, 0.008);
  g.gain.exponentialRampToValueAtTime(0.0001, 0.11);
  const g2 = ctx.createGain();
  g2.gain.value = 0.15;
  osc.connect(g);
  osc2.connect(g2).connect(g);
  g.connect(ctx.destination);
  osc.start(0);
  osc.stop(0.15);
  osc2.start(0);
  osc2.stop(0.15);
}

/** 成功音: メジャーアルペジオ+ベルのきらめき */
function renderSuccess(ctx: OfflineAudioContext) {
  const bus = reverbBus(ctx, 0.35, 1.2, 2.4);
  const note = (t: number, freq: number, dur: number, loud: number) => {
    for (const [type, ratio, amp] of [
      ['sine', 1, 1],
      ['triangle', 2, 0.3],
    ] as const) {
      const osc = ctx.createOscillator();
      osc.type = type;
      osc.frequency.value = freq * ratio;
      const g = ctx.createGain();
      adsr(g.gain, t, { a: 0.01, d: 0.08, s: 0.5, r: 0.25, dur, peak: loud * amp });
      osc.connect(g).connect(bus.input);
      osc.start(t);
      osc.stop(t + dur + 0.4);
    }
  };
  // ド ミ ソ ド↑
  note(0.02, 523.25, 0.12, 0.35);
  note(0.14, 659.25, 0.12, 0.35);
  note(0.26, 783.99, 0.12, 0.35);
  note(0.38, 1046.5, 0.4, 0.4);
}

// ------------------------------------------------------------- public API

const RENDERERS: Record<SynthSound, { seconds: number; render: (ctx: OfflineAudioContext) => void }> = {
  clap: { seconds: 1.8, render: renderClap },
  animal: { seconds: 1.0, render: renderAnimal },
  car: { seconds: 2.0, render: renderCar },
  sparkle: { seconds: 2.2, render: renderSparkle },
  trumpet: { seconds: 2.2, render: renderTrumpet },
  tap: { seconds: 0.2, render: renderTap },
  success: { seconds: 1.6, render: renderSuccess },
};

const bufferCache = new Map<SynthSound, Promise<AudioBuffer>>();

function getBuffer(kind: SynthSound): Promise<AudioBuffer> {
  let cached = bufferCache.get(kind);
  if (!cached) {
    const { seconds, render } = RENDERERS[kind];
    const offline = new OfflineAudioContext(2, Math.ceil(seconds * SAMPLE_RATE), SAMPLE_RATE);
    render(offline);
    cached = offline.startRendering();
    bufferCache.set(kind, cached);
  }
  return cached;
}

/**
 * 効果音を再生する(ナレーションとは独立の並行再生)。
 * fire-and-forget想定。ユーザージェスチャー後に呼ぶこと。
 */
export function playSound(kind: SynthSound): void {
  void getBuffer(kind)
    .then((buffer) => {
      const ctx = getAudioContext();
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(ctx.destination);
      src.start();
    })
    .catch(() => {
      // 合成失敗時は無音のまま(致命的ではない)
    });
}

/** 全効果音を先にレンダリングしてキャッシュ(初回再生の遅延防止) */
export function prewarmSounds(): void {
  (Object.keys(RENDERERS) as SynthSound[]).forEach((k) => void getBuffer(k));
}
