import type { CSSProperties, ReactNode } from 'react';
import './BigButton.css';

interface BigButtonProps {
  children: ReactNode;
  onClick: () => void;
  color?: 'primary' | 'accent' | 'green' | 'red' | 'ghost';
  disabled?: boolean;
  style?: CSSProperties;
}

/** 子どもの指でも押しやすい巨大タップターゲットの共通ボタン */
export function BigButton({
  children,
  onClick,
  color = 'primary',
  disabled = false,
  style,
}: BigButtonProps) {
  return (
    <button
      className={`big-button big-button--${color} pressable`}
      onClick={onClick}
      disabled={disabled}
      style={style}
    >
      {children}
    </button>
  );
}
