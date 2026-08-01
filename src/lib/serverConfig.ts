/**
 * Mac mini 対話サーバーの接続先URL管理。
 * 優先順位: 親モードでの手動設定(localStorage) > ビルド時の VITE_TALK_SERVER_URL > localhost。
 * Tailscale経由のアドレス(例: http://mac-mini.tailnet-xxxx.ts.net:8788)を親モードで設定する想定。
 */

const STORAGE_KEY = 'talk-server-url';
const DEFAULT_URL =
  (import.meta.env.VITE_TALK_SERVER_URL as string | undefined) || 'http://localhost:8788';

export function getTalkServerUrl(): string {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) return saved.replace(/\/+$/, '');
  } catch {
    // プライベートブラウズ等でlocalStorage不可の場合はデフォルトを使う
  }
  return DEFAULT_URL.replace(/\/+$/, '');
}

export function setTalkServerUrl(url: string): void {
  try {
    const trimmed = url.trim();
    if (trimmed) {
      localStorage.setItem(STORAGE_KEY, trimmed);
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // 保存できなくても致命的ではない
  }
}
