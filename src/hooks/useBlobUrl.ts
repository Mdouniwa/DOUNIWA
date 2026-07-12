import { useEffect, useState } from 'react';

/** BlobからオブジェクトURLを作り、破棄まで面倒を見るフック */
export function useBlobUrl(blob: Blob | null | undefined): string | null {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!blob) {
      setUrl(null);
      return;
    }
    const objectUrl = URL.createObjectURL(blob);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [blob]);

  return url;
}
