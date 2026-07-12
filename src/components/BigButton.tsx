import type { CSSProperties, ReactNode } from 'react';
import { playSound } from '../lib/soundEffects';
import './BigButton.css';

interface BigButtonProps {
  children: ReactNode;
  onClick: () => void;
  color?: 'primary' | 'accent' | 'green' | 'red' | 'ghost';
  disabled?: boolean;
  /** タップ音を鳴らさない(効果音・録音操作と混ざる場面用) */
  silent?: boolean;
  style?: CSSProperties;
}

/** 子どもの指でも押しやすい巨大タップターゲットの共通ボタン(タップ音つき) */
export function BigButton({
  children,
  onClick,
  color = 'primary',
  disabled = false,
  silent = false,
  style,
}: BigButtonProps) {
  return (
    <button
      className={`big-button big-button--${color} pressable`}
      onClick={() => {
        if (!silent) playSound('tap');
        onClick();
      }}
      disabled={disabled}
      style={style}
    >
      {children}
    </button>
  );
}
