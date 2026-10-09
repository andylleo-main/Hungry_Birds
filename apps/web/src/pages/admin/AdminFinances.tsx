import { useEffect, useState } from 'react';
import { ApiError, api } from '../../lib/api';
import type { MoneySplit, PayoutWeek, VendorFinances } from '../../lib/api';
import { Legend, SplitBar, weekLabel } from './AdminPayouts';
import type { Vendor } from '../../lib/types';
import { EmptyState, ErrorRetry, Icon, PageLoader } from '../../components/ui';
import { Panel, RangePicker, SectionHeading, StatTile, inr } from './parts';

const FIN_RANGES = [
  { days: 1, label: 'Today' },
  { days: 7, label: 'Week' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
];

function Cell({ split, strong = false, testid }: { split: MoneySplit; strong?: boolean; testid: string }) {
  // A dash rather than ₹0 when nothing happened in this cell, as the merchant app does.
  const empty = split.orders === 0;
  return (
    <td className={`px-space-sm py-space-md text-right align-top ${strong ? 'bg-surface-container/60' : ''}`} data-testid={testid}>
      <span className={`block font-display tabular-nums ${strong ? 'text-title-md' : 'text-body-md'} ${empty ? 'text-on-surface-variant' : 'text-on-surface'}`}>
        {empty ? '—' : inr(split.revenue)}
      </span>
      {!empty && (
        <span className="text-label-sm text-on-surface-variant">
          {split.orders} {split.orders === 1 ? 'order' : 'orders'}
        </span>
      )}
    </td>
  );
}

function MoneyGrid({ t }: { t: VendorFinances['totals'] }) {
  const paid = { orders: t.dine_in.orders + t.delivery.orders, revenue: t.revenue };
  const rows: { label: string; icon?: string; cells: MoneySplit[]; key: string }[] = [
    { key: 'dine-in', label: 'Dine in', icon: 'restaurant', cells: [t.dine_in_prepaid, t.dine_in_cash, t.dine_in] },
    { key: 'delivery', label: 'Delivery', icon: 'delivery_dining', cells: [t.delivery_prepaid, t.delivery_cash, t.delivery] },
    { key: 'total', label: 'Total', cells: [t.prepaid, t.cash, paid] },
  ];
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[460px] border-separate border-spacing-0" data-testid="finance-money-grid">
        <thead>
          <tr className="text-label-sm uppercase text-on-surface-variant">
            <th className="py-space-sm text-left font-bold" />
            <th className="px-space-sm py-space-sm text-right font-bold">Prepaid</th>
            <th className="px-space-sm py-space-sm text-right font-bold">Cash</th>
            <th className="bg-surface-container/60 px-space-sm py-space-sm text-right font-bold text-on-surface">Total</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className={r.key === 'total' ? '[&>*]:border-t-2 [&>*]:border-on-surface' : '[&>*]:border-t [&>*]:border-outline'}>
              <th className="py-space-md text-left align-top">
                <span className={`flex items-center gap-space-xs ${r.key === 'total' ? 'font-display text-title-md' : 'text-label-lg'}`}>
                  {r.icon && <Icon name={r.icon} className="text-[16px] text-primary" />}
                  {r.label}
                </span>
              </th>
              {r.cells.map((c, i) => (
                <Cell key={i} split={c} strong={r.key === 'total' || i === 2} testid={`finance-cell-${r.key}-${['prepaid', 'cash', 'total'][i]}`} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DayBars({ days }: { days: VendorFinances['orders_by_day'] }) {
  const peak = Math.max(0, ...days.map((d) => d.revenue));
  const recent = days.slice(-14);
  return (
    <div className="flex flex-col gap-space-xs">
      {recent.map((d) => (
        <div key={d.day} className="grid grid-cols-[64px_1fr_86px] items-center gap-space-sm text-body-sm">
          <span className="text-on-surface-variant">
            {new Date(`${d.day}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
          </span>
          <span className="h-3 overflow-hidden rounded-full bg-surface-container">
            <span className="block h-full rounded-full bg-primary transition-[width] duration-700" style={{ width: `${peak ? (d.revenue / peak) * 100 : 0}%` }} />
          </span>
          <span className="text-right tabular-nums">{inr(d.revenue)} · {d.orders}</span>
        </div>
      ))}
    </div>
  );
}

function StallPayouts({ vendorId }: { vendorId: string }) {
  const [weeks, setWeeks] = useState<PayoutWeek[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setWeeks(null);
    setFailed(false);
    api.payouts(8, vendorId).then((r) => setWeeks(r.weeks)).catch(() => setFailed(true));
  }, [vendorId]);

  return (
    <Panel title="Weekly payouts" subtitle="Prepaid via Razorpay next to cash already in the stall's hands, Monday to Sunday." action={<Legend />}>
      {failed ? (
        <p className="text-body-sm text-on-surface-variant">We couldn't load the weekly payouts.</p>
      ) : !weeks ? (
        <PageLoader />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-body-sm" data-testid="stall-payouts-table">
            <thead>
              <tr className="text-label-sm uppercase text-on-surface-variant">
                <th className="py-space-sm text-left font-bold">Week</th>
                <th className="px-space-sm text-right font-bold text-primary">Prepaid</th>
                <th className="px-space-sm text-right font-bold text-on-surface">Cash in hand</th>
                <th className="px-space-sm text-right font-bold">Discounts</th>
                <th className="bg-primary-tint/60 px-space-sm text-right font-bold text-on-surface">Owed to stall</th>
              </tr>
            </thead>
            <tbody>
              {weeks.map((w) => {
                const p = w.stalls[0];
                return (
                  <tr key={w.week_start} className="border-t border-outline" data-testid={`stall-payout-week-${w.week_start}`}>
                    <td className="py-space-sm pr-space-md">
                      <p className="text-label-lg">{weekLabel(w)}</p>
                      {p && <div className="mt-[4px] max-w-[160px]"><SplitBar p={p} /></div>}
                    </td>
                    <td className="px-space-sm text-right font-display tabular-nums text-primary">{p ? inr(p.prepaid_online) : '—'}</td>
                    <td className="px-space-sm text-right font-display tabular-nums">{p?.cash_in_hand ? inr(p.cash_in_hand) : '—'}</td>
                    <td className="px-space-sm text-right tabular-nums text-on-surface-variant">{p?.discounts ? inr(p.discounts) : '—'}</td>
                    <td className="bg-primary-tint/60 px-space-sm text-right font-display tabular-nums">{p ? inr(p.owed_to_stall) : '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function StallFinance({ vendor, onViewOrders }: { vendor: Vendor; onViewOrders: () => void }) {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<VendorFinances | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    setData(null);
    try {
      setData(await api.vendorFinances(vendor.id, days));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't load this stall's finances.");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendor.id, days]);

  return (
    <div className="flex flex-col gap-space-lg" data-testid={`finance-view-${vendor.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-space-md rounded-lg bg-on-surface p-space-md text-white md:p-space-lg">
        <div>
          <p className="text-label-sm uppercase tracking-[0.14em] text-white/60">Finances for</p>
          <h3 className="font-display text-headline-md" data-testid="finance-stall-name">{vendor.stall_name}</h3>
        </div>
        <div className="flex flex-wrap items-center gap-space-sm">
          <RangePicker days={days} onChange={setDays} options={FIN_RANGES} testid="finance-range" />
          <button type="button" className="btn-primary h-10" onClick={onViewOrders} data-testid="finance-view-orders">
            <Icon name="receipt_long" className="text-[18px]" /> View orders
          </button>
        </div>
      </div>

      {error ? (
        <ErrorRetry message={error} onRetry={load} />
      ) : !data ? (
        <PageLoader />
      ) : (
        <FinanceBody data={data} />
      )}
      <StallPayouts vendorId={vendor.id} />
    </div>
  );
}

function FinanceBody({ data }: { data: VendorFinances }) {
  const t = data.totals;
  const paidOrders = t.dine_in.orders + t.delivery.orders;
  const refusal = t.orders ? Math.round((t.refused_orders / t.orders) * 100) : null;
  return (
    <>
      <div className="grid grid-cols-2 gap-space-sm lg:grid-cols-4">
        <StatTile icon="payments" label="Total earned" value={inr(t.revenue)} tone="red" hint={`from ${paidOrders} paid ${paidOrders === 1 ? 'order' : 'orders'}`} testid="finance-revenue" />
        <StatTile icon="receipt_long" label="Orders placed" value={String(t.orders)} hint={`${t.active_orders} in progress now`} testid="finance-orders" />
        <StatTile icon="calculate" label="Average order" value={paidOrders ? inr(t.revenue / paidOrders) : '—'} testid="finance-average" />
        <StatTile icon="block" label="Turned away" value={refusal === null ? '—' : `${refusal}%`} hint={t.refused_orders ? `${inr(t.refused_value)} across ${t.refused_orders}` : 'Nothing refused'} testid="finance-refused" />
      </div>

      <Panel
        title="Where the money came from"
        subtitle={`Every row and column adds up to the ${inr(t.revenue)} earned. Same breakdown as the stall's merchant app.`}
      >
        <MoneyGrid t={t} />
        <p className="flex gap-space-xs rounded-md bg-surface-container px-space-md py-space-sm text-body-sm text-on-surface-variant">
          <Icon name="info" className="mt-[1px] text-[16px] text-primary" />
          A pay-on-delivery order paid by UPI QR counts as prepaid, because that money goes through Razorpay and not
          into the stall's cash box. Dine-in is always paid upfront, so dine-in cash stays at zero.
        </p>
      </Panel>

      <div className="grid gap-space-sm md:grid-cols-2">
        <StatTile
          icon="hourglass_top"
          label="Still to collect"
          value={t.outstanding.orders ? inr(t.outstanding.revenue) : '—'}
          tone={t.outstanding.orders ? 'warn' : 'plain'}
          hint={t.outstanding.orders ? `${t.outstanding.orders} pay-on-delivery ${t.outstanding.orders === 1 ? 'order' : 'orders'} not paid yet` : 'No money owed right now'}
          testid="finance-outstanding"
        />
        <StatTile
          icon="undo"
          label="Refunded"
          value={t.refunded.orders ? inr(t.refunded.revenue) : '—'}
          hint={t.refunded.orders ? `${t.refunded.orders} ${t.refunded.orders === 1 ? 'order' : 'orders'} refunded to customers` : 'No refunds in this period'}
          testid="finance-refunded"
        />
      </div>

      <div className="grid gap-space-md lg:grid-cols-2">
        <Panel title="Best sellers" subtitle="Across every size, by quantity sold.">
          {data.top_dishes.length === 0 ? (
            <p className="text-body-sm text-on-surface-variant">Nothing sold in this period yet.</p>
          ) : (
            <ol className="flex flex-col gap-space-sm" data-testid="finance-top-dishes">
              {data.top_dishes.map((d, i) => (
                <li key={`${d.name}-${d.variant_name}`} className="flex items-center gap-space-sm text-body-sm">
                  <span className="w-6 font-display font-bold text-primary">{i + 1}</span>
                  <span className="flex-1 truncate">{d.name}{d.variant_name ? ` · ${d.variant_name}` : ''}</span>
                  <span className="font-semibold">{d.quantity}×</span>
                  <span className="w-20 text-right tabular-nums text-on-surface-variant">{inr(d.revenue)}</span>
                </li>
              ))}
            </ol>
          )}
        </Panel>
        <Panel title="Day by day" subtitle="Money earned and orders placed, most recent 14 days.">
          <DayBars days={data.orders_by_day} />
        </Panel>
      </div>
    </>
  );
}

export default function AdminFinances({
  vendors,
  vendorId,
  onSelect,
  onViewOrders,
}: {
  vendors: Vendor[];
  vendorId: string;
  onSelect: (id: string) => void;
  onViewOrders: (id: string) => void;
}) {
  const selected = vendors.find((v) => v.id === vendorId) ?? vendors[0];

  return (
    <div data-testid="admin-finances">
      <SectionHeading
        eyebrow="Per stall"
        title="Finances"
        subtitle="Pick a stall to see how much it earned, split by dine-in and delivery and by prepaid and cash."
      />
      {vendors.length === 0 ? (
        <EmptyState icon="account_balance" title="No approved stalls yet" message="Once you approve a stall, its finances show up here." />
      ) : (
        <div className="grid gap-space-lg lg:grid-cols-[260px_1fr]">
          <div className="flex gap-space-xs overflow-x-auto pb-space-xs lg:flex-col lg:overflow-visible" data-testid="finance-stall-list">
            {vendors.map((v) => (
              <button
                key={v.id}
                type="button"
                data-testid={`finance-stall-${v.id}`}
                onClick={() => onSelect(v.id)}
                className={`flex shrink-0 items-center gap-space-sm rounded-md border px-space-md py-space-sm text-left transition-colors duration-200 ${
                  selected?.id === v.id ? 'border-primary bg-primary text-white' : 'border-outline bg-white hover:border-primary/40'
                }`}
              >
                <span className={`h-2 w-2 shrink-0 rounded-full ${v.is_open ? 'bg-success' : 'bg-on-surface-variant/40'}`} />
                <span className="truncate text-label-lg">{v.stall_name}</span>
              </button>
            ))}
          </div>
          {selected && <StallFinance vendor={selected} onViewOrders={() => onViewOrders(selected.id)} />}
        </div>
      )}
    </div>
  );
}
