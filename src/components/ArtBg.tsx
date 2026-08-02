import './ArtBg.css';

interface ArtBgProps {
  src: string;
  /** 内容の可読性を上げる薄い白ベールの強さ */
  veil?: 'none' | 'light' | 'strong';
}

/**
 * 画面全体に敷くアート背景。
 * 親の .screen に has-art-bg クラスを付けて使う(セーフエリアの外側まで敷かれ、
 * CSSの角花飾りは自動で消える)。装飾なので支援技術からは隠す。
 */
export function ArtBg({ src, veil = 'light' }: ArtBgProps) {
  return (
    <div className={`art-bg art-bg--veil-${veil}`} aria-hidden>
      <img src={src} alt="" draggable={false} loading="eager" decoding="async" />
    </div>
  );
}
