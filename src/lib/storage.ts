/**
 * iOS Safariの7日間未使用データ削除(ITP)対策として、
 * 起動時にストレージの永続化を要求する。
 * ホーム画面追加済みPWAでは通常許可される。
 */
export async function requestPersistentStorage(): Promise<boolean> {
  try {
    if (navigator.storage?.persist) {
      const persisted = await navigator.storage.persisted();
      if (persisted) return true;
      return await navigator.storage.persist();
    }
  } catch {
    // 非対応環境では黙って諦める(動作自体は継続できる)
  }
  return false;
}
