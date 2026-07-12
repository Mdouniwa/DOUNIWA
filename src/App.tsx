import { useCallback, useEffect, useState } from 'react';
import type { Route } from './routes';
import { unlockAudio } from './lib/audioUnlock';
import { HomeScreen } from './screens/HomeScreen';
import { CreateFlow } from './screens/create/CreateFlow';

export function App() {
  const [route, setRoute] = useState<Route>({ name: 'home' });

  const navigate = useCallback((next: Route) => {
    setRoute(next);
    window.scrollTo(0, 0);
  }, []);

  // iOS自動再生制限の解除: 初回タップでAudioContextをアンロック
  useEffect(() => {
    const handler = () => {
      void unlockAudio();
    };
    // アンロックは冪等なので毎タップ呼んでも安全(初回失敗時のリトライを兼ねる)
    window.addEventListener('pointerdown', handler);
    return () => window.removeEventListener('pointerdown', handler);
  }, []);

  switch (route.name) {
    case 'home':
      return <HomeScreen navigate={navigate} />;
    case 'create':
      return <CreateFlow navigate={navigate} />;
    case 'player':
      return <PlaceholderScreen label="よむ(Phase 3で実装)" navigate={navigate} />;
    case 'parent':
      return <PlaceholderScreen label="おやモード(Phase 4で実装)" navigate={navigate} />;
  }
}

// 各Phaseで実装するまでの仮画面
function PlaceholderScreen({
  label,
  navigate,
}: {
  label: string;
  navigate: (route: Route) => void;
}) {
  return (
    <div className="screen" style={{ alignItems: 'center', justifyContent: 'center', gap: 24 }}>
      <p style={{ fontSize: 24 }}>{label}</p>
      <button
        className="pressable"
        style={{ fontSize: 20, color: 'var(--color-accent)' }}
        onClick={() => navigate({ name: 'home' })}
      >
        ホームへもどる
      </button>
    </div>
  );
}
