import { useCallback, useEffect, useState } from 'react';
import type { Route } from './routes';
import { unlockAudio } from './lib/audioUnlock';
import { HomeScreen } from './screens/HomeScreen';
import { CreateFlow } from './screens/create/CreateFlow';
import { PlayerScreen } from './screens/PlayerScreen';
import { ParentScreen } from './screens/ParentScreen';

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
      return <PlayerScreen bookId={route.bookId} navigate={navigate} />;
    case 'parent':
      return <ParentScreen navigate={navigate} />;
  }
}
