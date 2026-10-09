import type { ReactNode } from 'react';
import { Icon } from '../../components/ui';

export const RANGES = [
  { days: 1, label: 'Today' },
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
];

export const inr = (n: number) => `₹${Math.round(n).toLocaleString('en-IN')}`;

export function RangePicker({
  days,
  onChange,
  options = RANGES,
  testid = 'range',
}: {
  days: number;
  onChange: (d: number) => void;
  options?: { days: number; label: string }[];
  testid?: string;
}) {
  return (
    <div className="inline-flex w-fit rounded-full border border-outline bg-white p-[3px]" role="group" aria-label="Date range">
      {options.map((r) => (
        <button
          key={r.days}
          type="button"
          data-testid={`${testid}-${r.days}`}
          aria-pressed={days === r.days}
          onClick={() => onChange(r.days)}
          className={`rounded-full px-space-md py-[6px] text-label-md transition-colors duration-200 ${
            days === r.days ? 'bg-on-surface text-white' : 'text-on-surface-medium hover:text-primary'
          }`}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}

export function StatTile({
  icon,
  label,
  value,
  hint,
  tone = 'plain',
  testid,
}: {
  icon: string;
  label: string;
  value: string;
  hint?: string;
  tone?: 'plain' | 'red' | 'dark' | 'warn';
  testid?: string;
}) {
  const tones = {
    plain: 'bg-white border-outline text-on-surface',
    red: 'bg-primary border-primary text-white',
    dark: 'bg-on-surface border-on-surface text-white',
    warn: 'bg-warning-tint border-warning/25 text-on-surface',
  };
  const sub = tone === 'red' || tone === 'dark' ? 'text-white/75' : 'text-on-surface-variant';
  return (
    <div className={`flex animate-rise flex-col gap-space-xs rounded-lg border p-space-md ${tones[tone]}`} data-testid={testid}>
      <div className={`flex items-center gap-space-xs ${sub}`}>
        <Icon name={icon} className="text-[18px]" />
        <span className="text-label-md">{label}</span>
      </div>
      <p className="font-display text-headline-lg tabular-nums">{value}</p>
      {hint && <p className={`text-body-sm ${sub}`}>{hint}</p>}
    </div>
  );
}

export function Panel({ title, subtitle, action, children }: { title: string; subtitle?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="card flex flex-col gap-space-md p-space-md md:p-space-lg">
      <div className="flex flex-wrap items-start justify-between gap-space-sm">
        <div className="flex flex-col gap-[2px]">
          <h3 className="text-title-md text-on-surface">{title}</h3>
          {subtitle && <p className="text-body-sm text-on-surface-variant">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function SectionHeading({ eyebrow, title, subtitle, action }: { eyebrow: string; title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="mb-space-lg flex flex-wrap items-end justify-between gap-space-md">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h2 className="mt-space-xs text-headline-lg text-on-surface">{title}</h2>
        {subtitle && <p className="mt-[2px] max-w-2xl text-body-sm text-on-surface-variant">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
