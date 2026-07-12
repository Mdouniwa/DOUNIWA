/** アプリ内の画面遷移(React Router不使用、App.tsxの状態機械で切替) */
export type Route =
  | { name: 'home' }
  | { name: 'create' }
  | { name: 'player'; bookId: string }
  | { name: 'parent' };

export type Navigate = (route: Route) => void;
