import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import { App } from './App';
import { requestPersistentStorage } from './lib/storage';

// iOSの7日間未使用データ削除対策: 起動時に永続化を要求
void requestPersistentStorage();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
