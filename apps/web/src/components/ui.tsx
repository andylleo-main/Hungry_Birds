import { useEffect } from 'react';
import type { ReactNode } from 'react';

/**
 * Material Symbols renders via ligature, so the glyph name sits in the DOM as
 * text. aria-hidden keeps it out of accessible names - without it a button
 * reading "Add" announces as "add Add" to a screen reader.
 */
export function Icon({ name, className = '' }: { name: string; className?: string }) {
  return (
    <span aria-hidden="true" className={`material-symbols-outlined ${className}`}>
      {name}
    </span>
  );
}

export function Spinner({ className = '' }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={`inline-block h-5 w-5 animate-spin rounded-full border-2 border-current border-t-transparent ${className}`}
    />
  );
}

export function PageLoader() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <Spinner className="h-8 w-8 text-primary" />
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  message,
  action,
}: {
  icon: string;
  title: string;
  message: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-space-sm rounded-lg border border-dashed border-outline px-space-lg py-space-xl text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-surface-container">
        <Icon name={icon} className="text-[28px] text-on-surface-variant" />
      </span>
      <h3 className="text-headline-sm text-on-surface">{title}</h3>
      <p className="max-w-sm text-body-sm text-on-surface-variant">{message}</p>
      {action}
    </div>
  );
}

export function ErrorRetry({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-space-sm rounded-lg border border-outline-variant bg-primary-tint/40 px-space-lg py-space-xl text-center">
      <Icon name="error" className="text-[28px] text-primary" />
      <p className="max-w-sm text-body-sm text-on-surface-medium">{message}</p>
      <button type="button" className="btn-secondary" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

/** Segmented -/qty/+ control from the spec's Quantity Increment Counter. */
export function QuantityStepper({
  quantity,
  onChange,
  compact = false,
}: {
  quantity: number;
  onChange: (next: number) => void;
  compact?: boolean;
}) {
  const size = compact ? 'h-8' : 'h-9';
  return (
    <div className={`inline-flex ${size} items-center rounded-full bg-surface-container`}>
      <button
        type="button"
        aria-label="Decrease quantity"
        onClick={() => onChange(quantity - 1)}
        className={`flex ${size} w-8 items-center justify-center rounded-full text-on-surface transition-colors hover:bg-surface-container-high`}
      >
        <Icon name="remove" className="text-[16px]" />
      </button>
      <span className="min-w-[24px] text-center text-label-md text-on-surface">{quantity}</span>
      <button
        type="button"
        aria-label="Increase quantity"
        onClick={() => onChange(quantity + 1)}
        className={`flex ${size} w-8 items-center justify-center rounded-full text-on-surface transition-colors hover:bg-surface-container-high`}
      >
        <Icon name="add" className="text-[16px]" />
      </button>
    </div>
  );
}

/**
 * A bottom sheet on a phone, a centred card on a desktop.
 *
 * The app had no modal, dialog or sheet of any kind, so this is the first.
 * Geometry follows MobileCartBar (fixed to the bottom edge, `shadow-sheet`) and
 * the click-away pattern from the header's account menu. z-50 and below are
 * already taken by the fixed header and the mobile cart bar, so this sits above
 * both.
 *
 * Escape closes it and the backdrop is a real button rather than a div, because
 * a sheet you can only leave by making a choice is a trap on a page somebody
 * opened by accident.
 */
export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60]">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-black/40"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="absolute inset-x-0 bottom-0 max-h-[80vh] overflow-y-auto rounded-t-xl bg-surface-container-lowest p-space-md shadow-sheet sm:inset-x-auto sm:bottom-auto sm:left-1/2 sm:top-1/2 sm:w-[28rem] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl"
      >
        <div className="mb-space-sm flex items-center justify-between">
          <h3 className="text-headline-sm text-on-surface">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-8 w-8 items-center justify-center rounded-full text-on-surface-variant hover:bg-surface-container"
          >
            <Icon name="close" className="text-[20px]" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
