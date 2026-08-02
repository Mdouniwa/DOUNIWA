import { useState } from 'react';
import type { Navigate } from '../../routes';
import type { Draft, DraftPage } from './draft';
import type { TalkTurn } from '../../lib/talkApi';
import { ProgressDots } from '../../components/ProgressDots';
import { ArtBg } from '../../components/ArtBg';
import { ART } from '../../lib/artAssets';
import { TalkScreen } from './TalkScreen';
import { Generating } from './Generating';
import { ReviewPages } from './ReviewPages';
import { CoverSetup } from './CoverSetup';
import { Done } from './Done';
import './create.css';

type Step = 'talk' | 'generating' | 'review' | 'cover' | 'done';

// 進捗ドットを表示するステップ(対話・生成中・完了は独自表示のため除く)
const DOT_STEPS: Step[] = ['review', 'cover'];

interface CreateFlowProps {
  navigate: Navigate;
}

/** 作成フロー: えほんの精と対話 → AI生成 → できあがり確認 → 表紙 → 完了 */
export function CreateFlow({ navigate }: CreateFlowProps) {
  const [step, setStep] = useState<Step>('talk');
  const [draft, setDraft] = useState<Draft>({
    theme: 'odekake',
    pages: [],
    coverPageId: null,
    title: '',
    conversation: [],
    characterRef: null,
  });

  const goHome = () => navigate({ name: 'home' });
  const updateDraft = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const back = () => {
    switch (step) {
      case 'review':
        // もういちど おはなしを つくりなおす(対話からやり直し)
        updateDraft({ conversation: [], pages: [], characterRef: null });
        setStep('talk');
        break;
      case 'cover':
        setStep('review');
        break;
      default:
        goHome();
        break;
    }
  };

  // 対話完了: 対話ログを下書きへ取り込み生成に進む
  const handleTalkDone = (conversation: TalkTurn[]) => {
    updateDraft({ conversation });
    setStep('generating');
  };

  // 生成完了: 物語・ページ・基準画像を下書きに取り込む
  const handleGenerated = (
    title: string,
    pages: DraftPage[],
    characterRef: Draft['characterRef'],
  ) => {
    updateDraft({
      title,
      pages,
      characterRef,
      coverPageId: pages[0]?.id ?? null,
    });
    setStep('review');
  };

  const showHeader = step === 'review' || step === 'cover';
  // 対話・生成中ステップは内側が独自に.screen(アート背景つき)を持つため、
  // 外側の余白・角飾りを外して二重パディングを防ぐ
  const bare = step === 'talk' || step === 'generating';

  return (
    <div className={`screen create-screen${bare ? ' create-screen--bare' : ' has-art-bg'}`}>
      {/* 確認・表紙・完了ステップは外殻に強めのベール付き背景を敷いて世界観を統一 */}
      {!bare && <ArtBg src={ART.bgHome} veil="strong" />}
      {showHeader && (
        <header className="create-header">
          <button className="create-back pressable" onClick={back}>
            ←もどる
          </button>
          <ProgressDots total={DOT_STEPS.length} current={DOT_STEPS.indexOf(step)} />
          <span className="create-header-spacer" />
        </header>
      )}

      {step === 'talk' && <TalkScreen onDone={handleTalkDone} onQuit={goHome} />}
      {step === 'generating' && (
        <Generating
          conversation={draft.conversation}
          onDone={handleGenerated}
          onBack={() => setStep('talk')}
        />
      )}
      {step === 'review' && (
        <ReviewPages
          pages={draft.pages}
          onChange={(pages) => updateDraft({ pages })}
          onNext={() => setStep('cover')}
        />
      )}
      {step === 'cover' && (
        <CoverSetup draft={draft} onChange={updateDraft} onSaved={() => setStep('done')} />
      )}
      {step === 'done' && <Done onHome={goHome} />}
    </div>
  );
}
