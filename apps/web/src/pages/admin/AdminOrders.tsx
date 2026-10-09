import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../../lib/api';
import type { AdminOrder } from '../../lib/api';
import type { OrderStatus, Vendor } from '../../lib/types';
import { FULFILMENT_LABEL, STATUS_LABEL, paymentLabel } from '../../lib/types';
import { dayAndTime, displayPhone, rupees } from '../../lib/format';
import { EmptyState, ErrorRetry, Icon, PageLoader, Sheet } from '../../components/ui';
import { RangePicker, SectionHeading, StatTile, inr } from './parts';

const STATUS_FILTERS: OrderStatus[] = [
  'placed',
  'accepted',
  'preparing',
  'ready',
  'out_for_delivery',
  'completed',
  'rejected',
  'cancelled',
  'awaiting_payment',
];

/** How the money arrived, in the merchant app's terms: a doorstep UPI scan is prepaid. */
export function paymentKind(o: Pick<AdminOrder, 'payment_method' | 'collected_via' | 'payment_status'>) {
  if (o.payment_method !== 'cod') return { label: 'Prepaid online', tone: 'text-success' };
  if (o.collected_via === 'cash') return { label: 'Cash on delivery', tone: 'text-warning' };
  if (o.collected_via === 'upi') return { label: 'On delivery, UPI (prepaid)', tone: 'text-success' };
  if (o.payment_status === 'due') return { label: 'On delivery, not collected', tone: 'text-warning' };
  return { label: 'Pay on delivery', tone: 'text-on-surface-variant' };
}

function statusTone(s: OrderStatus) {
  if (s === 'completed') return 'bg-success/10 text-success';
  if (s === 'rejected' || s === 'cancelled') return 'bg-surface-container text-on-surface-variant';
  if (s === 'awaiting_payment') return 'bg-warning/10 text-warning';
  return 'bg-primary-tint text-primary';
}

function OrderDetail({ order }: { order: AdminOrder }) {
  const pay = paymentKind(order);
  const rows: [string, string][] = [
    ['Stall', order.stall_name ?? '—'],
    ['Placed', dayAndTime(order.created_at)],
    ['Status', STATUS_LABEL[order.status] ?? order.status],
    ['Type', FULFILMENT_LABEL[order.fulfilment_type]],
    ...(order.delivery_location_label ? [['Deliver to', order.delivery_location_label] as [string, string]] : []),
    ['Payment', `${pay.label} · ${paymentLabel(order.payment_status)}`],
    ['Customer', [order.customer_name, order.customer_phone && displayPhone(order.customer_phone)].filter(Boolean).join(' · ') || '—'],
    ...(order.rider_name || order.self_delivery
      ? [['Delivered by', order.self_delivery ? 'The stall itself' : `${order.rider_name}${order.rider_phone ? ` · ${displayPhone(order.rider_phone)}` : ''}`] as [string, string]]
      : []),
  ];
  return (
    <div className="flex flex-col gap-space-md" data-testid="admin-order-detail">
      <dl className="grid grid-cols-[110px_1fr] gap-x-space-md gap-y-space-sm text-body-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-on-surface-variant">{k}</dt>
            <dd className="text-on-surface">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="dotted-rule" />
      <ul className="flex flex-col gap-space-xs">
        {order.items.map((i) => (
          <li key={i.id} className="flex justify-between gap-space-md text-body-sm">
            <span>
              {i.quantity}× {i.name_snapshot}
              {i.variant_name_snapshot ? ` · ${i.variant_name_snapshot}` : ''}
            </span>
            <span className="tabular-nums">{rupees(Number(i.price_snapshot) * i.quantity)}</span>
          </li>
        ))}
      </ul>
      <div className="dotted-rule" />
      <div className="flex flex-col gap-[2px] text-body-sm">
        <div className="flex justify-between font-semibold"><span>Order total</span><span>{rupees(order.total_amount)}</span></div>
        {Number(order.cashback_applied ?? 0) > 0 && (
          <div className="flex justify-between text-on-surface-variant"><span>Cashback used</span><span>−{rupees(order.cashback_applied!)}</span></div>
        )}
        {Number(order.coupon_discount ?? 0) > 0 && (
          <div className="flex justify-between text-on-surface-variant"><span>Coupon</span><span>−{rupees(order.coupon_discount!)}</span></div>
        )}
        <div className="flex justify-between text-on-surface-variant"><span>Customer paid</span><span>{rupees(order.amount_due ?? order.total_amount)}</span></div>
      </div>
      {order.note && <p className="rounded-md bg-surface-container p-space-sm text-body-sm">Note: {order.note}</p>}
    </div>
  );
}

function OrderLine({ order, onOpen }: { order: AdminOrder; onOpen: () => void }) {
  const pay = paymentKind(order);
  return (
    <button
      type="button"
      onClick={onOpen}
      data-testid={`admin-order-row-${order.id}`}
      className="grid w-full grid-cols-[1fr_auto] items-center gap-space-md border-b border-outline-variant px-space-md py-space-md text-left transition-colors last:border-0 hover:bg-primary-tint/50 md:grid-cols-[1.3fr_1fr_0.9fr_1.1fr_0.7fr]"
    >
      <div className="min-w-0">
        <p className="truncate text-label-lg text-on-surface">
          #{order.order_number}
          {order.token_number ? <span className="ml-space-xs text-on-surface-variant">· token {order.token_number}</span> : null}
        </p>
        <p className="truncate text-body-sm text-on-surface-variant">{order.stall_name} · {dayAndTime(order.created_at)}</p>
      </div>
      <div className="hidden md:block">
        <span className={`badge ${statusTone(order.status)}`}>{STATUS_LABEL[order.status] ?? order.status}</span>
      </div>
      <p className="hidden text-body-sm text-on-surface-medium md:block">
        {FULFILMENT_LABEL[order.fulfilment_type]}
        {order.delivery_location_label ? ` · ${order.delivery_location_label}` : ''}
      </p>
      <p className={`hidden text-label-md md:block ${pay.tone}`}>{pay.label}</p>
      <p className="text-right font-display text-title-md tabular-nums">{rupees(order.total_amount)}</p>
    </button>
  );
}

export default function AdminOrders({
  vendors,
  vendorId,
  onVendorChange,
}: {
  vendors: Vendor[];
  vendorId: string;
  onVendorChange: (id: string) => void;
}) {
  const [days, setDays] = useState(1);
  const [status, setStatus] = useState<OrderStatus | ''>('');
  const [query, setQuery] = useState('');
  const [orders, setOrders] = useState<AdminOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<AdminOrder | null>(null);

  async function load() {
    setError(null);
    setOrders(null);
    try {
      setOrders(await api.adminOrders({ vendorId: vendorId || undefined, status: status || undefined, days }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't load the orders.");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days, status, vendorId]);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!orders || !needle) return orders ?? [];
    return orders.filter(
      (o) =>
        o.order_number.toLowerCase().includes(needle) ||
        (o.customer_name ?? '').toLowerCase().includes(needle) ||
        o.items.some((i) => i.name_snapshot.toLowerCase().includes(needle)),
    );
  }, [orders, query]);

  const live = shown.filter((o) => !['completed', 'rejected', 'cancelled', 'awaiting_payment'].includes(o.status)).length;
  const value = shown.filter((o) => o.payment_status === 'paid').reduce((s, o) => s + Number(o.total_amount), 0);

  return (
    <div data-testid="admin-orders">
      <SectionHeading
        eyebrow="Every stall"
        title="Orders"
        subtitle="Every order from every stall. Filter by stall, status or date, and tap one to see what's in it."
        action={<RangePicker days={days} onChange={setDays} testid="admin-orders-range" />}
      />

      <div className="mb-space-md flex flex-wrap gap-space-sm">
        <select className="field h-11 w-auto min-w-[200px]" value={vendorId} onChange={(e) => onVendorChange(e.target.value)} data-testid="admin-orders-stall-select">
          <option value="">All stalls</option>
          {vendors.map((v) => (
            <option key={v.id} value={v.id}>{v.stall_name}</option>
          ))}
        </select>
        <select className="field h-11 w-auto min-w-[170px]" value={status} onChange={(e) => setStatus(e.target.value as OrderStatus | '')} data-testid="admin-orders-status-select">
          <option value="">Any status</option>
          {STATUS_FILTERS.map((s) => (
            <option key={s} value={s}>{STATUS_LABEL[s]}</option>
          ))}
        </select>
        <div className="relative min-w-[220px] flex-1">
          <Icon name="search" className="absolute left-space-md top-1/2 -translate-y-1/2 text-[20px] text-on-surface-variant" />
          <input className="field h-11 pl-[44px]" placeholder="Order number, customer or dish" value={query} onChange={(e) => setQuery(e.target.value)} data-testid="admin-orders-search" />
        </div>
      </div>

      {error ? (
        <ErrorRetry message={error} onRetry={load} />
      ) : !orders ? (
        <PageLoader />
      ) : (
        <>
          <div className="mb-space-md grid grid-cols-3 gap-space-sm">
            <StatTile icon="receipt_long" label="Orders" value={String(shown.length)} testid="admin-orders-count" />
            <StatTile icon="local_fire_department" label="In progress" value={String(live)} tone="red" testid="admin-orders-live" />
            <StatTile icon="payments" label="Paid value" value={inr(value)} tone="dark" testid="admin-orders-value" />
          </div>
          {shown.length === 0 ? (
            <EmptyState icon="receipt_long" title="No orders here" message="Nothing matches these filters. Try a longer date range or another stall." />
          ) : (
            <div className="card overflow-hidden" data-testid="admin-orders-list">
              <div className="hidden grid-cols-[1.3fr_1fr_0.9fr_1.1fr_0.7fr] gap-space-md border-b border-outline bg-surface-container px-space-md py-space-sm text-label-sm uppercase text-on-surface-variant md:grid">
                <span>Order</span><span>Status</span><span>Type</span><span>Payment</span><span className="text-right">Total</span>
              </div>
              {shown.map((o) => (
                <OrderLine key={o.id} order={o} onOpen={() => setOpen(o)} />
              ))}
            </div>
          )}
          {orders.length >= 200 && (
            <p className="mt-space-sm text-body-sm text-on-surface-variant">Showing the latest 200. Pick a stall or a shorter range to see the rest.</p>
          )}
        </>
      )}

      <Sheet open={open !== null} onClose={() => setOpen(null)} title={open ? `Order #${open.order_number}` : ''}>
        {open && <OrderDetail order={open} />}
      </Sheet>
    </div>
  );
}
