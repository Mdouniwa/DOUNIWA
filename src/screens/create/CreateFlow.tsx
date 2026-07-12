import { useState } from 'react';
import type { Navigate } from '../../routes';
import type { Theme } from '../../types';
import type { Draft } from './draft';
import { ProgressDots } from '../../components/ProgressDots';
import { TemplateSelect } from './TemplateSelect';
import { PhotoPick } from './PhotoPick';
import { PageOrder } from './PageOrder';
import { RecordPages } from './RecordPages';
import { CoverSetup } from './CoverSetup';
import { Done } from './Done';
import './create.css';

const TOTAL_STEPS = 6;

interface CreateFlowProps {
  navigate: Navigate;
}

/** 作成フロー: 1画面1タスク、進捗ドット付きのステップウィザード */
export function CreateFlow({ navigate }: CreateFlowProps) {
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<Draft>({
    theme: 'odekake',
    pages: [],
    coverPageId: null,
    title: '',
  });

  const goHome = () => navigate({ name: 'home' });
  const next = () => setStep((s) => Math.min(s + 1, TOTAL_STEPS - 1));
  const back = () => {
    if (step === 0) {
      goHome();
    } else {
      setStep((s) => s - 1);
    }
  };

  const updateDraft = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  return (
    <div className="screen create-screen">
      {step < TOTAL_STEPS - 1 && (
        <header className="create-header">
          <button className="create-back pressable" onClick={back}>
            ←もどる
          </button>
          <ProgressDots total={TOTAL_STEPS} current={step} />
          <span className="create-header-spacer" />
        </header>
      )}

      {step === 0 && (
        <TemplateSelect
          theme={draft.theme}
          onSelect={(theme: Theme) => {
            updateDraft({ theme });
            next();
          }}
        />
      )}
      {step === 1 && (
        <PhotoPick
          pages={draft.pages}
          onChange={(pages) => updateDraft({ pages })}
          onNext={next}
        />
      )}
      {step === 2 && (
        <PageOrder
          pages={draft.pages}
          onChange={(pages) => updateDraft({ pages })}
          onNext={next}
        />
      )}
      {step === 3 && (
        <RecordPages
          pages={draft.pages}
          onChange={(pages) => updateDraft({ pages })}
          onNext={next}
        />
      )}
      {step === 4 && (
        <CoverSetup draft={draft} onChange={updateDraft} onSaved={next} />
      )}
      {step === 5 && <Done onHome={goHome} />}
    </div>
  );
}
