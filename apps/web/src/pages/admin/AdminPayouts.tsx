import { useEffect, useState } from 'react';
import { ApiError, api } from '../../lib/api';
import type { PayoutWeek, StallPayout } from '../../lib/api';
import { EmptyState, ErrorRetry, Icon, PageLoader } from '../../components/ui';
import { SectionHeading, StatTile, inr } from './parts';

const WEEKS = 8;

export function weekLabel(w: Pick<PayoutWeek, 'week_start' | 'week_end'>) {
  const f = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
  return `${f(w.week_start)} – ${f(w.week_end)}`;
}

/** Prepaid and cash as one bar, so the split reads at a glance. */
export function SplitBar({ p }: { p: StallPayout }) {
  const total = p.prepaid_online + p.cash_in_hand + p.discounts;
  const pct = (n: number) => (total ? `${(n / total) * 100}%` : '0%');
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-surface-container" aria-hidden>
      <span className="bg-primary" style={{ width: pct(p.prepaid_online) }} />
      <span className="bg-on-surface" style={{ width: pct(p.cash_in_hand) }} />
      <span className="bg-warning" style={{ width: pct(p.discounts) }} />
    </div>
  );
}

export function Legend() {
  return (
    <div className="flex flex-wrap gap-space-md text-label-md text-on-surface-variant">
      <span className="flex items-center gap-space-xs"><span className="h-2.5 w-2.5 rounded-full bg-primary" /> Prepaid via Razorpay</span>
      <span className="flex items-center gap-space-xs"><span className="h-2.5 w-2.5 rounded-full bg-on-surface" /> Cash in hand</span>
      <span className="flex items-center gap-space-xs"><span className="h-2.5 w-2.5 rounded-full bg-warning" /> Discounts we fund</span>
    </div>
  );
}

function PayoutRow({ p, onOpen }: { p: StallPayout; onOpen?: () => void }) {
  return (
    <tr className="border-t border-outline align-top" data-testid={`payout-row-${p.vendor_id}`}>
      <td className="py-space-md pr-space-md">
        <button type="button" onClick={onOpen} className="text-left text-label-lg text-on-surface transition-colors hover:text-primary" data-testid={`payout-stall-${p.vendor_id}`}>
          {p.stall_name}
        </button>
        <p className="text-body-sm text-on-surface-variant">{p.orders} paid {p.orders === 1 ? 'order' : 'orders'}</p>
        <div className="mt-space-xs max-w-[180px]"><SplitBar p={p} /></div>
      </td>
      <td className="px-space-sm py-space-md text-right font-display tabular-nums text-primary">{inr(p.prepaid_online)}</td>
      <td className="px-space-sm py-space-md text-right font-display tabular-nums">{p.cash_in_hand ? inr(p.cash_in_hand) : '—'}</td>
      <td className="px-space-sm py-space-md text-right tabular-nums text-on-surface-variant">{p.discounts ? inr(p.discounts) : '—'}</td>
      <td className="px-space-sm py-space-md text-right tabular-nums">{inr(p.order_value)}</td>
      <td className="bg-primary-tint/60 px-space-sm py-space-md text-right font-display text-title-md tabular-nums" data-testid={`payout-owed-${p.vendor_id}`}>{inr(p.owed_to_stall)}</td>
    </tr>
  );
}

export default function AdminPayouts({ onOpenStall }: { onOpenStall: (id: string) => void }) {
  const [weeks, setWeeks] = useState<PayoutWeek[] | null>(null);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    setWeeks(null);
    try {
      setWeeks((await api.payouts(WEEKS)).weeks);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't load the payouts.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const week = weeks?.[index];

  return (
    <div data-testid="admin-payouts">
      <SectionHeading
        eyebrow="Settlement"
        title="Weekly payouts"
        subtitle="For each stall, money that came in online through Razorpay next to the cash it already collected. Weeks run Monday to Sunday."
      />
      {error ? (
        <ErrorRetry message={error} onRetry={load} />
      ) : !weeks || !week ? (
        <PageLoader />
      ) : (
        <div className="flex flex-col gap-space-lg">
          <div className="flex flex-wrap items-center justify-between gap-space-sm rounded-lg bg-on-surface p-space-sm pl-space-md text-white">
            <div>
              <p className="text-label-sm uppercase tracking-[0.14em] text-white/60">{index === 0 ? 'This week' : index === 1 ? 'Last week' : `${index} weeks ago`}</p>
              <p className="font-display text-headline-sm" data-testid="payout-week-label">{weekLabel(week)}</p>
            </div>
            <div className="flex gap-space-xs">
              <button type="button" disabled={index >= weeks.length - 1} onClick={() => setIndex((i) => i + 1)} className="flex h-10 w-10 items-center justify-center rounded-full bg-white/10 transition-colors hover:bg-primary disabled:opacity-30" aria-label="Previous week" data-testid="payout-prev-week">
                <Icon name="chevron_left" className="text-[22px]" />
              </button>
              <button type="button" disabled={index === 0} onClick={() => setIndex((i) => i - 1)} className="flex h-10 w-10 items-center justify-center rounded-full bg-white/10 transition-colors hover:bg-primary disabled:opacity-30" aria-label="Next week" data-testid="payout-next-week">
                <Icon name="chevron_right" className="text-[22px]" />
              </button>
            </div>
          </div>

          {week.totals ? (
            <>
              <div className="grid grid-cols-2 gap-space-sm lg:grid-cols-4">
                <StatTile icon="account_balance" label="Prepaid via Razorpay" value={inr(week.totals.prepaid_online)} tone="red" testid="payout-total-prepaid" />
                <StatTile icon="payments" label="Cash in hand" value={inr(week.totals.cash_in_hand)} tone="dark" hint="already with the stalls" testid="payout-total-cash" />
                <StatTile icon="redeem" label="Discounts we fund" value={inr(week.totals.discounts)} hint="cashback and coupons" testid="payout-total-discounts" />
                <StatTile icon="handshake" label="Owed to stalls" value={inr(week.totals.owed_to_stall)} hint="order value minus cash in hand" testid="payout-total-owed" />
              </div>

              <section className="card p-space-md md:p-space-lg">
                <div className="mb-space-sm flex flex-wrap items-center justify-between gap-space-sm">
                  <h3 className="text-title-md">By stall</h3>
                  <Legend />
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[720px] text-body-sm" data-testid="payout-table">
                    <thead>
                      <tr className="text-label-sm uppercase text-on-surface-variant">
                        <th className="py-space-sm text-left font-bold">Stall</th>
                        <th className="px-space-sm py-space-sm text-right font-bold text-primary">Prepaid (Razorpay)</th>
                        <th className="px-space-sm py-space-sm text-right font-bold text-on-surface">Cash in hand</th>
                        <th className="px-space-sm py-space-sm text-right font-bold">Discounts</th>
                        <th className="px-space-sm py-space-sm text-right font-bold">Order value</th>
                        <th className="bg-primary-tint/60 px-space-sm py-space-sm text-right font-bold text-on-surface">Owed to stall</th>
                      </tr>
                    </thead>
                    <tbody>
                      {week.stalls.map((p) => (
                        <PayoutRow key={p.vendor_id} p={p} onOpen={() => onOpenStall(p.vendor_id)} />
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t-2 border-on-surface font-semibold">
                        <td className="py-space-md font-display text-title-md">All stalls</td>
                        <td className="px-space-sm text-right tabular-nums text-primary">{inr(week.totals.prepaid_online)}</td>
                        <td className="px-space-sm text-right tabular-nums">{inr(week.totals.cash_in_hand)}</td>
                        <td className="px-space-sm text-right tabular-nums">{inr(week.totals.discounts)}</td>
                        <td className="px-space-sm text-right tabular-nums">{inr(week.totals.order_value)}</td>
                        <td className="bg-primary-tint/60 px-space-sm text-right font-display text-title-md tabular-nums">{inr(week.totals.owed_to_stall)}</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
                <p className="mt-space-md flex gap-space-xs rounded-md bg-surface-container px-space-md py-space-sm text-body-sm text-on-surface-variant">
                  <Icon name="info" className="mt-[1px] text-[16px] text-primary" />
                  Cash in hand is what a stall collected in notes on delivery, so it's already in their cash box. A
                  doorstep UPI scan counts as prepaid. Cashback and coupons are paid for by Hungry Birds, so a stall is
                  owed its full order value minus the cash it already holds.
                </p>
              </section>
            </>
          ) : (
            <EmptyState icon="event_busy" title="No paid orders this week" message="Use the arrows to look at another week." />
          )}
        </div>
      )}
    </div>
  );
}
