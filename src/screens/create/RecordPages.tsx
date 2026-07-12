import { useEffect, useRef, useState } from 'react';
import type { DraftPage } from './draft';
import type { SoundEffect } from '../../types';
import { SOUND_EFFECT_EMOJI, SOUND_EFFECT_LABELS } from '../../types';
import { useRecorder } from '../../hooks/useRecorder';
import { useBlobUrl } from '../../hooks/useBlobUrl';
import { playSound, prewarmSounds } from '../../lib/soundEffects';
import { BigButton } from '../../components/BigButton';

const EFFECTS: SoundEffect[] = ['clap', 'animal', 'car', 'sparkle', 'trumpet'];

interface RecordPagesProps {
  pages: DraftPage[];
  onChange: (pages: DraftPage[]) => void;
  onNext: () => void;
}

/** Step4: ページごとの録音 + 効果音選択 */
export function RecordPages({ pages, onChange, onNext }: RecordPagesProps) {
  const [index, setIndex] = useState(0);
  const recorder = useRecorder();
  const previewRef = useRef<HTMLAudioElement | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const page = pages[index];
  const imageUrl = useBlobUrl(page?.imageBlob);

  // 効果音プレビューの初回遅延を避けるため先にレンダリング
  useEffect(() => {
    prewarmSounds();
  }, []);

  // ページ移動・アンマウント時にプレビュー停止
  const stopPreview = () => {
    previewRef.current?.pause();
    previewRef.current = null;
    setPreviewing(false);
  };
  useEffect(() => stopPreview, [index]);

  if (!page) return null;

  const updatePage = (patch: Partial<DraftPage>) => {
    onChange(pages.map((p, i) => (i === index ? { ...p, ...patch } : p)));
  };

  const toggleRecord = async () => {
    stopPreview();
    if (recorder.state === 'recording') {
      const result = await recorder.stop();
      if (result) {
        updatePage({ audioBlob: result.blob, audioMime: result.mime });
      }
    } else {
      // 録り直し: 前の録音は上書きされるので1タップで開始できる
      await recorder.start();
    }
  };

  const playPreview = () => {
    if (!page.audioBlob) return;
    stopPreview();
    const url = URL.createObjectURL(page.audioBlob);
    const audio = new Audio(url);
    previewRef.current = audio;
    setPreviewing(true);
    audio.onended = audio.onerror = () => {
      URL.revokeObjectURL(url);
      setPreviewing(false);
    };
    void audio.play();
  };

  const selectEffect = (effect: SoundEffect | null) => {
    updatePage({ soundEffect: effect });
    if (effect) playSound(effect);
  };

  const goPage = async (delta: -1 | 1) => {
    if (recorder.state === 'recording') await recorder.stop();
    stopPreview();
    setIndex((i) => Math.max(0, Math.min(pages.length - 1, i + delta)));
  };

  const isRecording = recorder.state === 'recording';
  const isLast = index === pages.length - 1;

  return (
    <div className="create-step">
      <h2 className="create-step-title">
        こえを いれよう({index + 1} / {pages.length})
      </h2>

      <div className="record-photo">{imageUrl && <img src={imageUrl} alt="" />}</div>

      <div className="record-controls">
        <button
          className={`record-button pressable ${isRecording ? 'record-button--recording' : ''}`}
          onClick={() => void toggleRecord()}
          aria-label={isRecording ? '録音を止める' : '録音する'}
        >
          {isRecording ? '⏹' : '🎤'}
        </button>
        <div className="record-status">
          {isRecording
            ? 'ろくおんちゅう… もういちど おすと とまるよ'
            : page.audioBlob
              ? 'とれたよ! 🎤で とりなおせるよ'
              : '🎤を おして おはなししてね'}
          {recorder.state === 'error' && (
            <span className="record-error">マイクが つかえないみたい</span>
          )}
        </div>
        {page.audioBlob && !isRecording && (
          <button className="record-preview pressable" onClick={playPreview}>
            {previewing ? '▶ さいせいちゅう…' : '▶ きいてみる'}
          </button>
        )}
      </div>

      <div className="effect-row">
        <p className="create-step-hint">タップしたときの おと</p>
        <div className="effect-chips">
          <button
            className={`effect-chip pressable ${page.soundEffect === null ? 'effect-chip--selected' : ''}`}
            onClick={() => selectEffect(null)}
          >
            なし
          </button>
          {EFFECTS.map((e) => (
            <button
              key={e}
              className={`effect-chip pressable ${page.soundEffect === e ? 'effect-chip--selected' : ''}`}
              onClick={() => selectEffect(e)}
            >
              <span aria-hidden>{SOUND_EFFECT_EMOJI[e]}</span> {SOUND_EFFECT_LABELS[e]}
            </button>
          ))}
        </div>
      </div>

      <div className="create-step-footer record-footer">
        {/* 録音中の可能性があるためタップ音は鳴らさない(マイクに乗るのを防ぐ) */}
        <BigButton color="ghost" silent onClick={() => void goPage(-1)} disabled={index === 0}>
          ← まえ
        </BigButton>
        {isLast ? (
          <BigButton color="green" silent onClick={onNext}>
            つぎへ →
          </BigButton>
        ) : (
          <BigButton color="accent" silent onClick={() => void goPage(1)}>
            つぎの ページ →
          </BigButton>
        )}
      </div>
    </div>
  );
}
