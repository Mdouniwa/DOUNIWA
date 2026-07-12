import { useBlobUrl } from '../../hooks/useBlobUrl';

/** 下書きページのサムネイル表示 */
export function PageThumb({ blob }: { blob: Blob }) {
  const url = useBlobUrl(blob);
  return (
    <div className="page-thumb">{url && <img src={url} alt="" draggable={false} />}</div>
  );
}
