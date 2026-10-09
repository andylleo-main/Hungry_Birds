import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import type { Order } from '../lib/types';
import { FULFILMENT_LABEL, paymentLabel, STATUS_LABEL, isActive } from '../lib/types';
import { dayAndTime, rupees } from '../lib/format';
import { EmptyState, ErrorRetry, Icon, PageLoader } from '../components/ui';

function OrderRow({ order, index }: { order: Order; index: number }) {
  const active = isActive(order.status);
  const names = order.items.map((i) => `${i.quantity}× ${i.name_snapshot}`).join(', ');

  return (
    <Link
      to={`/orders/${order.id}`}
      data-testid={`order-row-${order.id}`}
      style={{ animationDelay: `${Math.min(index, 8) * 50}ms` }}
      className={`group flex animate-rise items-center gap-space-md rounded-lg border bg-white p-space-md transition-[transform,box-shadow,border-color] duration-300 hover:-translate-y-0.5 hover:shadow-card-hover ${
        active ? 'border-primary/30' : 'border-outline'
      }`}
    >
      <span
        className={`flex h-12 w-12 shrink-0 flex-col items-center justify-center rounded-md font-display ${
          active ? 'bg-primary text-white' : 'bg-surface-container text-on-surface-variant'
        }`}
      >
        {order.token_number ? (
          <>
            <span className="text-[9px] font-bold uppercase tracking-wider opacity-80">Token</span>
            <span className="text-headline-sm leading-none">{order.token_number}</span>
          </>
        ) : (
          <Icon name="receipt_long" className="text-[22px]" />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-space-sm">
          <p className="truncate text-label-lg text-on-surface">#{order.order_number}</p>
          <span className={`badge ${active ? '' : 'bg-surface-container text-on-surface-variant'}`}>
            {STATUS_LABEL[order.status]}
          </span>
          <span className="text-label-sm uppercase text-on-surface-variant">{FULFILMENT_LABEL[order.fulfilment_type]}</span>
        </div>
        <p className="truncate text-body-sm text-on-surface-variant">{names}</p>
        <p className="text-label-md text-on-surface-variant/80">{dayAndTime(order.created_at)}</p>
      </div>

      <div className="shrink-0 text-right">
        <p className="font-display text-headline-sm text-on-surface">{rupees(order.amount_due ?? order.total_amount)}</p>
        <p className={`text-label-md ${order.payment_status === 'paid' ? 'text-success' : 'text-on-surface-variant'}`}>
          {paymentLabel(order.payment_status)}
        </p>
      </div>
      <Icon name="chevron_right" className="text-[20px] text-on-surface-variant transition-transform group-hover:translate-x-1" />
    </Link>
  );
}

export default function Orders() {
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    setOrders(null);
    try {
      setOrders(await api.myOrders());
    } catch {
      setError("We couldn't load your orders. Please try again.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const active = orders?.filter((o) => isActive(o.status)) ?? [];
  const past = orders?.filter((o) => !isActive(o.status)) ?? [];

  return (
    <div className="page" data-testid="orders-page">
      <span className="eyebrow"><Icon name="receipt_long" className="text-[16px]" /> Orders</span>
      <h1 className="mb-space-lg mt-space-xs text-headline-lg text-on-surface">Your orders</h1>

      {error ? (
        <ErrorRetry message={error} onRetry={load} />
      ) : !orders ? (
        <PageLoader />
      ) : orders.length === 0 ? (
        <EmptyState
          icon="receipt_long"
          title="No orders yet"
          message="Order from any campus stall and you can follow it here, live."
          action={
            <Link to="/" className="btn-primary mt-space-sm" data-testid="orders-browse-stalls">
              See the stalls
            </Link>
          }
        />
      ) : (
        <div className="flex flex-col gap-space-xl">
          {active.length > 0 && (
            <section data-testid="orders-active">
              <h2 className="mb-space-md flex items-center gap-space-sm text-headline-md text-on-surface">
                <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-primary" /> In progress
              </h2>
              <div className="flex flex-col gap-space-sm">
                {active.map((order, i) => (
                  <OrderRow key={order.id} order={order} index={i} />
                ))}
              </div>
            </section>
          )}

          {past.length > 0 && (
            <section data-testid="orders-past">
              <h2 className="mb-space-md text-headline-md text-on-surface">Past orders</h2>
              <div className="flex flex-col gap-space-sm">
                {past.map((order, i) => (
                  <OrderRow key={order.id} order={order} index={i} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
