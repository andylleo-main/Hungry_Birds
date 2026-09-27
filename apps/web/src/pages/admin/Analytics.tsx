import { useEffect, useState } from 'react';
import { ApiError, api } from '../../lib/api';
import type { Analytics as AnalyticsData } from '../../lib/api';
import { BarList, TimeSeries } from '../../components/charts';
import { ErrorRetry, Icon, PageLoader } from '../../components/ui';

const RANGES = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
];

const STATUS_LABELS: Record<string, string> = {
  placed: 'Placed',
  accepted: 'Accepted',
  preparing: 'Preparing',
  ready: 'Ready',
  completed: 'Completed',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
};

const rupees = (n: number) =>
  `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

/** "12 Sep" - short enough to sit under a tick without collisions. */
function dayLabel(iso: string) {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}

function StatTile({
  icon,
  label,
  value,
  hint,
}: {
  icon: string;
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="card flex flex-col gap-space-xs p-space-md">
      <div className="flex items-center gap-space-xs text-on-surface-variant">
        <Icon name={icon} className="text-[18px]" />
        <span className="text-label-md">{label}</span>
      </div>
      {/* The number is the point of a stat tile, so it gets the size. */}
      <p className="text-headline-lg text-on-surface tabular-nums">{value}</p>
      {hint && <p className="text-body-sm text-on-surface-variant">{hint}</p>}
    </div>
  );
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="card flex flex-col gap-space-md p-space-md">
      <div className="flex flex-col gap-1">
        <h3 className="text-title-md text-on-surface">{title}</h3>
        {subtitle && <p className="text-body-sm text-on-surface-variant">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

export default function Analytics() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showTable, setShowTable] = useState(false);

  async function load(range: number) {
    setError(null);
    setData(null);
    try {
      setData(await api.analytics(range));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load analytics.");
    }
  }

  useEffect(() => {
    void load(days);
  }, [days]);

  if (error) return <ErrorRetry message={error} onRetry={() => void load(days)} />;
  if (!data) return <PageLoader />;

  const { totals } = data;
  const orderPoints = data.orders_by_day.map((d) => ({
    label: dayLabel(d.day),
    value: d.orders,
    display: `${d.orders} ${d.orders === 1 ? 'order' : 'orders'}`,
  }));
  const revenuePoints = data.orders_by_day.map((d) => ({
    label: dayLabel(d.day),
    value: Math.round(d.revenue),
    display: rupees(d.revenue),
  }));

  return (
    <div className="flex flex-col gap-space-lg">
      {/* Filters in one row above the charts. */}
      <div className="flex flex-wrap items-center gap-space-xs">
        {RANGES.map((r) => (
          <button
            key={r.days}
            type="button"
            onClick={() => setDays(r.days)}
            aria-pressed={days === r.days}
            className={`rounded-full px-space-md py-space-xs text-label-md transition ${
              days === r.days
                ? 'bg-primary text-on-primary'
                : 'bg-surface-container text-on-surface-medium hover:bg-surface-container-high'
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-space-md lg:grid-cols-3">
        <StatTile
          icon="receipt_long"
          label="Orders"
          value={totals.orders.toLocaleString('en-IN')}
          hint={`in the last ${data.range_days} days`}
        />
        <StatTile
          icon="payments"
          label="Revenue"
          value={rupees(totals.revenue)}
          hint="cancelled orders excluded"
        />
        <StatTile
          icon="pending_actions"
          label="Active now"
          value={String(totals.active_orders)}
          hint="not yet collected"
        />
        <StatTile icon="group" label="Customers" value={totals.customers.toLocaleString('en-IN')} />
        <StatTile icon="storefront" label="Open stalls" value={String(totals.vendors)} />
        <StatTile
          icon="how_to_reg"
          label="Awaiting approval"
          value={String(totals.pending_vendors)}
          hint={totals.pending_vendors ? 'needs your attention' : 'all caught up'}
        />
      </div>

      {/* Two charts, not one with two axes: orders and rupees are different
          scales, and a shared axis would make their crossings meaningless. */}
      <div className="grid gap-space-md lg:grid-cols-2">
        <Panel title="Orders per day" subtitle="Every day in range, including quiet ones.">
          <TimeSeries points={orderPoints} ariaLabel="Orders per day" />
        </Panel>

        <Panel title="Revenue per day" subtitle="Cancelled orders are not counted.">
          <TimeSeries
            points={revenuePoints}
            ariaLabel="Revenue per day in rupees"
            formatValue={(v) => (v >= 1000 ? `₹${Math.round(v / 1000)}k` : `₹${v}`)}
          />
        </Panel>

        <Panel title="Where orders are" subtitle="Status mix across the range.">
          <BarList
            items={data.status_breakdown.map((s) => ({
              label: STATUS_LABELS[s.status] ?? s.status,
              value: s.count,
            }))}
            emptyLabel="No orders in this range yet."
          />
        </Panel>

        <Panel title="Busiest stalls" subtitle="By number of orders.">
          <BarList
            items={data.top_vendors.map((v) => ({
              label: v.stall_name,
              value: v.orders,
              display: `${v.orders} · ${rupees(v.revenue)}`,
            }))}
            emptyLabel="No stall has taken an order yet."
          />
        </Panel>
      </div>

      {/* The numbers behind the charts, for anyone who can't read them off a
          line - screen readers included. */}
      <div>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => setShowTable((v) => !v)}
          aria-expanded={showTable}
        >
          <Icon name={showTable ? 'expand_less' : 'table_rows'} className="text-[18px]" />
          {showTable ? 'Hide the numbers' : 'Show the numbers'}
        </button>

        {showTable && (
          <div className="card mt-space-sm overflow-x-auto p-space-md">
            <table className="w-full text-body-sm">
              <caption className="sr-only">Orders and revenue per day</caption>
              <thead>
                <tr className="text-left text-label-md text-on-surface-variant">
                  <th scope="col" className="py-space-xs pr-space-md">Day</th>
                  <th scope="col" className="py-space-xs pr-space-md text-right">Orders</th>
                  <th scope="col" className="py-space-xs text-right">Revenue</th>
                </tr>
              </thead>
              <tbody>
                {data.orders_by_day.map((d) => (
                  <tr key={d.day} className="border-t border-surface-container">
                    <td className="py-space-xs pr-space-md text-on-surface-medium">
                      {dayLabel(d.day)}
                    </td>
                    <td className="py-space-xs pr-space-md text-right tabular-nums">{d.orders}</td>
                    <td className="py-space-xs text-right tabular-nums">{rupees(d.revenue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
