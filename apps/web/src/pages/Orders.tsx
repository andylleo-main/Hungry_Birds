import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import type { Order } from '../lib/types';
import { PAYMENT_LABEL, STATUS_LABEL, isActive } from '../lib/types';
import { dayAndTime, rupees } from '../lib/format';
import { EmptyState, ErrorRetry, Icon, PageLoader } from '../components/ui';

function OrderRow({ order }: { order: Order }) {
  const active = isActive(order.status);


  return (
    <Link
      to={`/orders/${order.id}`}
      className="card flex items-center gap-space-md p-space-md transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
    >
      <span
        className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full ${
          active ? 'bg-primary-tint text-primary' : 'bg-surface-container text-on-surface-variant'
        }`}
      >
        <Icon name={active ? 'local_fire_department' : 'receipt_long'} className="text-[22px]" />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-space-sm">
          <p className="truncate text-label-lg text-on-surface">#{order.order_number}</p>
          <span
            className={`badge ${active ? '' : 'bg-surface-container text-on-surface-variant'}`}
          >
            {STATUS_LABEL[order.status]}
          </span>
        </div>
        <p className="truncate text-body-sm text-on-surface-variant">
          {order.items.length} {order.items.length === 1 ? 'item' : 'items'} ·{' '}
          {dayAndTime(order.created_at)}
        </p>
      </div>

      <div className="shrink-0 text-right">
        <p className="text-label-lg text-on-surface">{rupees(order.total_amount)}</p>
        <p
          className={`text-label-md ${
            order.payment_status === 'paid' ? 'text-success' : 'text-on-surface-variant'
          }`}
        >
          {PAYMENT_LABEL[order.payment_status]}
        </p>
      </div>
      <Icon name="chevron_right" className="text-[20px] text-on-surface-variant" />
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
      setError("Couldn't load your orders.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const active = orders?.filter((o) => isActive(o.status)) ?? [];
  const past = orders?.filter((o) => !isActive(o.status)) ?? [];

  return (
    <div className="mx-auto max-w-content px-margin-mobile py-space-lg md:px-margin md:py-space-xl">
      <h1 className="mb-space-lg text-headline-lg text-on-surface">Your orders</h1>

      {error ? (
        <ErrorRetry message={error} onRetry={load} />
      ) : !orders ? (
        <PageLoader />
      ) : orders.length === 0 ? (
        <EmptyState
          icon="receipt_long"
          title="No orders yet"
          message="When you order from a campus stall, it'll show up here with live status."
          action={
            <Link to="/" className="btn-primary mt-space-sm">
              Browse stalls
            </Link>
          }
        />
      ) : (
        <div className="flex flex-col gap-space-lg">
          {active.length > 0 && (
            <section>
              <h2 className="mb-space-md text-headline-md text-on-surface">Happening now</h2>
              <div className="flex flex-col gap-space-sm">
                {active.map((order) => (
                  <OrderRow key={order.id} order={order} />
                ))}
              </div>
            </section>
          )}

          {past.length > 0 && (
            <section>
              <h2 className="mb-space-md text-headline-md text-on-surface">Earlier</h2>
              <div className="flex flex-col gap-space-sm">
                {past.map((order) => (
                  <OrderRow key={order.id} order={order} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
