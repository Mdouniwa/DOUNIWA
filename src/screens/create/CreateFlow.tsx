import { useState } from 'react';
import type { Navigate } from '../../routes';
import type { Draft, DraftPage } from './draft';
import { categoryToTheme, iconByKeyword } from '../../lib/icons';
import { ProgressDots } from '../../components/ProgressDots';
import { IconSelect } from './IconSelect';
import { Generating } from './Generating';
import { ReviewPages } from './ReviewPages';
import { CoverSetup } from './CoverSetup';
import { Done } from './Done';
import './create.css';

type Step = 'icons' | 'generating' | 'review' | 'cover' | 'done';

// 進捗ドットを表示する対話ステップ(生成中・完了は除く)
const DOT_STEPS: Step[] = ['icons', 'review', 'cover'];

interface CreateFlowProps {
  navigate: Navigate;
}

/** 作成フロー: アイコン選択 → AI生成 → できあがり確認 → 表紙 → 完了 */
export function CreateFlow({ navigate }: CreateFlowProps) {
  const [step, setStep] = useState<Step>('icons');
  const [draft, setDraft] = useState<Draft>({
    theme: 'odekake',
    pages: [],
    coverPageId: null,
    title: '',
    iconKeywords: [],
  });

  const goHome = () => navigate({ name: 'home' });
  const updateDraft = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const back = () => {
    switch (step) {
      case 'icons':
        goHome();
        break;
      case 'review':
        setStep('icons');
        break;
      case 'cover':
        setStep('review');
        break;
      default:
        break;
    }
  };

  // 生成完了: 物語・ページを下書きに取り込み、テーマ・表紙を初期設定
  const handleGenerated = (title: string, pages: DraftPage[]) => {
    const firstIcon = iconByKeyword(draft.iconKeywords[0]);
    updateDraft({
      title,
      pages,
      coverPageId: pages[0]?.id ?? null,
      theme: firstIcon ? categoryToTheme(firstIcon.category) : 'odekake',
    });
    setStep('review');
  };

  const showHeader = step === 'icons' || step === 'review' || step === 'cover';

  return (
    <div className="screen create-screen">
      {showHeader && (
        <header className="create-header">
          <button className="create-back pressable" onClick={back}>
            ←もどる
          </button>
          <ProgressDots total={DOT_STEPS.length} current={DOT_STEPS.indexOf(step)} />
          <span className="create-header-spacer" />
        </header>
      )}

      {step === 'icons' && (
        <IconSelect
          selected={draft.iconKeywords}
          onChange={(iconKeywords) => updateDraft({ iconKeywords })}
          onNext={() => setStep('generating')}
        />
      )}
      {step === 'generating' && (
        <Generating
          iconKeywords={draft.iconKeywords}
          onDone={handleGenerated}
          onBack={() => setStep('icons')}
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
