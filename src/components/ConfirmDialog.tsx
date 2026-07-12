import type { ReactNode } from 'react';
import { BigButton } from './BigButton';
import './ConfirmDialog.css';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** 親モードの削除などに使う確認ダイアログ */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'はい',
  cancelLabel = 'やめる',
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;
  return (
    <div className="confirm-overlay" onClick={onCancel}>
      <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
        <h2 className="confirm-title">{title}</h2>
        {message && <div className="confirm-message">{message}</div>}
        <div className="confirm-actions">
          <BigButton color="ghost" onClick={onCancel}>
            {cancelLabel}
          </BigButton>
          <BigButton color={danger ? 'red' : 'primary'} onClick={onConfirm}>
            {confirmLabel}
          </BigButton>
        </div>
      </div>
    </div>
  );
}
