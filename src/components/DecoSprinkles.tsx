import type { CSSProperties } from 'react';
import { deco, type DecoName } from '../lib/artAssets';
import './DecoSprinkles.css';

export interface DecoItem {
  name: DecoName;
  /** 位置・大きさ・回転(top/left/right/bottom/width/transform など) */
  style: CSSProperties;
  /**
   * 表示ティア: 1 = 常に表示 / 2 = 480px以下で非表示 / 3 = 700px以下で非表示。
   * 小さい画面では自動的に装飾が減り、操作を邪魔しない。
   */
  tier?: 1 | 2 | 3;
}

/**
 * 画面の余白に散りばめる装飾イラスト。
 * pointer-events: none なのでタップ領域は一切邪魔しない。装飾なので支援技術からは隠す。
 */
export function DecoSprinkles({ items }: { items: DecoItem[] }) {
  return (
    <div className="deco-sprinkles" aria-hidden>
      {items.map((item, i) => (
        <img
          key={`${item.name}-${i}`}
          className={`deco-sprinkle deco-tier-${item.tier ?? 1}`}
          src={deco(item.name)}
          alt=""
          draggable={false}
          loading="lazy"
          decoding="async"
          style={item.style}
        />
      ))}
    </div>
  );
}
