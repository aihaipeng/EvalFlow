import React from "react";
import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import * as DialogPrimitive from "@radix-ui/react-dialog";

export function ModalDialog({
  title,
  children,
  onClose,
  footer,
  className = "",
  description,
}) {
  const returnFocus = React.useRef(null);

  function restoreFocus(event) {
    event.preventDefault();
    const target = returnFocus.current;
    window.requestAnimationFrame(() => {
      if (target?.isConnected) target.focus();
    });
  }

  return (
    <DialogPrimitive.Root open onOpenChange={(open) => !open && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="overlay radix-dialog-overlay" />
        <DialogPrimitive.Content
          className={`modal modal-wide radix-dialog-content ${className}`.trim()}
          onOpenAutoFocus={() => {
            returnFocus.current = document.activeElement;
          }}
          onCloseAutoFocus={restoreFocus}
        >
          <DialogPrimitive.Title className="modal-header">
            {title}
          </DialogPrimitive.Title>
          {description ? (
            <DialogPrimitive.Description className="radix-dialog-description">
              {description}
            </DialogPrimitive.Description>
          ) : null}
          <div className="modal-body">{children}</div>
          <div className="modal-footer">
            {footer || (
              <DialogPrimitive.Close asChild>
                <button className="btn btn-secondary" type="button">
                  关闭
                </button>
              </DialogPrimitive.Close>
            )}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel = "确认",
  secondaryLabel,
  onConfirm,
  onSecondary,
  onClose,
  busy = false,
  danger = false,
}) {
  const returnFocus = React.useRef(null);

  function restoreFocus(event) {
    event.preventDefault();
    const target = returnFocus.current;
    window.requestAnimationFrame(() => {
      if (target?.isConnected) target.focus();
    });
  }

  async function confirm(event) {
    event.preventDefault();
    if (busy) return;
    const shouldClose = await onConfirm();
    if (shouldClose !== false) onClose();
  }

  async function secondary(event) {
    event.preventDefault();
    if (busy || !onSecondary) return;
    const shouldClose = await onSecondary();
    if (shouldClose !== false) onClose();
  }

  return (
    <AlertDialogPrimitive.Root
      open={open}
      onOpenChange={(nextOpen) => !nextOpen && !busy && onClose()}
    >
      <AlertDialogPrimitive.Portal>
        <AlertDialogPrimitive.Overlay className="overlay radix-dialog-overlay" />
        <AlertDialogPrimitive.Content
          className="modal modal-sm execution-modal is-confirm radix-dialog-content"
          onOpenAutoFocus={() => {
            returnFocus.current = document.activeElement;
          }}
          onCloseAutoFocus={restoreFocus}
        >
          <AlertDialogPrimitive.Title className="modal-header">
            {title}
          </AlertDialogPrimitive.Title>
          <AlertDialogPrimitive.Description asChild>
            <div className="modal-body execution-confirm-copy">{children}</div>
          </AlertDialogPrimitive.Description>
          <div className="modal-footer">
            <AlertDialogPrimitive.Cancel asChild>
              <button className="btn btn-secondary" type="button" disabled={busy}>
                取消
              </button>
            </AlertDialogPrimitive.Cancel>
            {secondaryLabel && onSecondary ? (
              <button
                className="btn btn-secondary"
                type="button"
                disabled={busy}
                onClick={secondary}
              >
                {secondaryLabel}
              </button>
            ) : null}
            <AlertDialogPrimitive.Action asChild>
              <button
                className={`btn ${danger ? "btn-danger" : "btn-primary"}`}
                type="button"
                disabled={busy}
                onClick={confirm}
              >
                {busy ? "处理中…" : confirmLabel}
              </button>
            </AlertDialogPrimitive.Action>
          </div>
        </AlertDialogPrimitive.Content>
      </AlertDialogPrimitive.Portal>
    </AlertDialogPrimitive.Root>
  );
}
