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
