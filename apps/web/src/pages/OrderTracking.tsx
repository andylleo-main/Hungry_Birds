import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { CHECKOUT_THEME, openCheckout } from '../lib/razorpay';
import { ApiError, api, orderSocketUrl } from '../lib/api';
import type { FulfilmentType, Order, OrderStatus } from '../lib/types';
import { paymentLabel, STATUS_LABEL, isActive, isMockPayment } from '../lib/types';
import { dayAndTime, rupees, timeOfDay } from '../lib/format';
import { ErrorRetry, Icon, PageLoader, Spinner } from '../components/ui';

type Step = { status: OrderStatus; icon: string; blurb: string };

/**
 * The happy path, in order. Rejected/cancelled are terminal detours.
 *
 * Built per order rather than fixed, because the two kinds of order genuinely
 * have different steps: a delivery gains an out-for-delivery stage and ends with
 * somebody arriving, a dine-in ends at the counter.
 */
function timelineFor(fulfilment: FulfilmentType): Step[] {
  const start: Step[] = [
    { status: 'awaiting_payment', icon: 'credit_card', blurb: 'Waiting for your payment' },
    { status: 'placed', icon: 'receipt_long', blurb: 'Sent to the stall' },
    { status: 'accepted', icon: 'check_circle', blurb: 'The stall confirmed your order' },
    { status: 'preparing', icon: 'skillet', blurb: 'Being cooked right now' },
  ];
  if (fulfilment === 'delivery') {
    return [
      ...start,
      { status: 'ready', icon: 'shopping_bag', blurb: 'Packed and ready to go out' },
      { status: 'out_for_delivery', icon: 'delivery_dining', blurb: 'On its way to you' },
      { status: 'completed', icon: 'done_all', blurb: 'Delivered and paid' },
    ];
  }
  return [
    ...start,
    { status: 'ready', icon: 'shopping_bag', blurb: 'Ready at the counter' },
    { status: 'completed', icon: 'done_all', blurb: 'Picked up and paid' },
  ];
}

export default function OrderTracking() {
  const { orderId = '' } = useParams();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [paying, setPaying] = useState(false);
  const [payError, setPayError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  async function load() {
    setError(null);
    try {
      setOrder(await api.order(orderId));
    } catch {
      setError("Couldn't load this order.");
    }
  }

  /**
   * Re-open Checkout for an order whose payment was never finished.
   *
   * The same Razorpay order is reused rather than a new one being created, so a
   * customer who closed the sheet, lost signal or came back tomorrow cannot end
   * up with two payments against one plate of food.
   */
  async function resumePayment() {
    setPaying(true);
    setPayError(null);
    try {
      const session = await api.paymentSession(orderId);
      if (isMockPayment(session)) {
        await api.confirmMockPayment(orderId);
        await load();
        setPaying(false);
        return;
      }

      // Re-read rather than assume, whichever way the sheet closes: paying is
      // confirmed by the webhook, and dismissing says nothing at all.
      const refresh = () => {
        void load().finally(() => setPaying(false));
      };

      await openCheckout({
        key: session.key_id,
        amount: session.amount,
        currency: session.currency,
        name: 'Hungry Birds',
        description: order ? `Order ${order.order_number}` : 'Your order',
        order_id: session.gateway_order_id,
        notes: { order_number: order?.order_number ?? '' },
        theme: { color: CHECKOUT_THEME },
        handler: (handback) => {
          void api
            .confirmPayment(orderId, handback)
            .catch(() => undefined)
            .finally(refresh);
        },
        modal: { ondismiss: refresh },
      });
      // Deliberately no setPaying(false) here: the sheet is open, not finished.
      // Both callbacks above clear it.
    } catch (err) {
      setPayError(
        err instanceof ApiError
          ? err.message
          : "Couldn't reopen the payment. Nothing was charged.",
      );
      setPaying(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId]);

  // Live status pushes. The socket is a nicety, not the source of truth -
  // load() above already fetched current state, and we refetch on reconnect.
  useEffect(() => {
    if (!orderId) return;
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;

    async function connect() {
      if (closed) return;

      let url: string;
      try {
        url = await orderSocketUrl(orderId);
      } catch {
        // No ticket (offline, rate limited, expired session) - the page still
        // works, it just falls back to the retry below instead of live pushes.
        setLive(false);
        if (!closed) retry = setTimeout(() => void connect(), 4000);
        return;
      }
      if (closed) return;

      const socket = new WebSocket(url);
      socketRef.current = socket;

      socket.onopen = () => setLive(true);
      socket.onmessage = (event) => {
        try {
          setOrder(JSON.parse(event.data) as Order);
        } catch {
          // Ignore anything that isn't an order payload.
        }
      };
      socket.onclose = () => {
        setLive(false);
        if (closed) return;
        // Resync on reconnect in case we missed a transition while away.
        retry = setTimeout(() => {
          void load();
          void connect();
        }, 4000);
      };
      socket.onerror = () => socket.close();
    }

    void connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      socketRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId]);

  if (error) {
    return (
      <div className="mx-auto max-w-content px-margin-mobile py-space-xl md:px-margin">
        <ErrorRetry message={error} onRetry={load} />
      </div>
    );
  }
  if (!order) return <PageLoader />;

  const timeline = timelineFor(order.fulfilment_type);
  const currentIndex = timeline.findIndex((s) => s.status === order.status);
  const derailed = order.status === 'rejected' || order.status === 'cancelled';


  return (
    <div className="mx-auto max-w-content px-margin-mobile py-space-lg md:px-margin md:py-space-xl">
      <Link
        to="/orders"
        className="mb-space-md inline-flex items-center gap-space-xs text-label-md text-on-surface-variant hover:text-on-surface"
      >
        <Icon name="arrow_back" className="text-[18px]" />
        All orders
      </Link>

      {order.payment_status === 'due' && (
        <div className="card mb-space-lg flex flex-wrap items-center gap-space-md border-[1.5px] border-outline-variant p-space-md">
          <Icon name="payments" className="text-[26px] text-on-surface-variant" />
          <div className="min-w-0 flex-1">
            <p className="text-label-lg text-on-surface">
              Pay {rupees(order.total_amount)} when it arrives
            </p>
            <p className="text-body-sm text-on-surface-variant">
              Cash, or scan the rider's UPI code at the door. The stall is already
              making this - nothing is owed until it reaches you.
            </p>
          </div>
        </div>
      )}

      {order.status === 'awaiting_payment' && (
        <div className="card mb-space-lg flex flex-wrap items-center gap-space-md border-[1.5px] border-primary bg-primary-tint/40 p-space-md">
          <Icon name="credit_card" className="text-[26px] text-primary" />
          <div className="min-w-0 flex-1">
            <p className="text-label-lg text-on-surface">This order isn't paid for yet</p>
            <p className="text-body-sm text-on-surface-variant">
              The stall hasn't seen it and won't start cooking until the payment goes
              through. Nothing has been charged so far.
            </p>
            {payError && (
              <p className="mt-space-xs text-body-sm text-primary">{payError}</p>
            )}
          </div>
          <button
            type="button"
            className="btn-primary shrink-0"
            disabled={paying}
            onClick={resumePayment}
          >
            {paying ? <Spinner /> : <>Finish paying {rupees(order.total_amount)}</>}
          </button>
        </div>
      )}

      {order.payment_status === 'refund_pending' && (
        <p className="card mb-space-lg p-space-md text-body-sm text-on-surface-variant">
          Your refund is on its way back to the account you paid from. Banks usually
          take a few working days.
        </p>
      )}

      {/* Header strip */}
      <div className="card mb-space-lg flex flex-wrap items-center justify-between gap-space-md p-space-md">
        <div className="flex items-center gap-space-md">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-tint">
            <Icon name="storefront" className="text-[24px] text-primary" />
          </span>
          <div>
            <div className="flex items-center gap-space-sm">
              <h1 className="text-headline-sm text-on-surface">Order #{order.order_number}</h1>
              {live && isActive(order.status) && (
                <span className="inline-flex items-center gap-space-xs text-label-sm uppercase text-success">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-success" />
                  Live
                </span>
              )}
            </div>
            <p className="text-body-sm text-on-surface-variant">
              Placed {dayAndTime(order.created_at)}
            </p>
          </div>
        </div>

        <div className="rounded-lg bg-surface-container px-space-md py-space-sm text-right">
          <p className="text-label-sm uppercase tracking-wide text-on-surface-variant">Status</p>
          <p
            className={`text-headline-sm ${derailed ? 'text-on-surface-variant' : 'text-primary'}`}
          >
            {STATUS_LABEL[order.status]}
          </p>
        </div>
      </div>

      <div className="grid gap-space-lg lg:grid-cols-[1fr_380px]">
        {/* Progress */}
        <div className="card p-space-md md:p-space-lg">
          <div className="mb-space-lg flex items-center justify-between">
            <h2 className="text-headline-md text-on-surface">Order progress</h2>
            <span
              className={`badge ${derailed ? 'bg-surface-container text-on-surface-variant' : ''}`}
            >
              {isActive(order.status) ? 'In progress' : STATUS_LABEL[order.status]}
            </span>
          </div>

          {derailed ? (
            <div className="flex items-start gap-space-md rounded-lg bg-surface-container p-space-md">
              <Icon name="cancel" className="text-[24px] text-on-surface-variant" />
              <div>
                <p className="text-label-lg text-on-surface">
                  {order.status === 'rejected'
                    ? 'The stall could not take this order'
                    : 'This order was cancelled'}
                </p>
                <p className="text-body-sm text-on-surface-variant">
                  {order.payment_status === 'refunded'
                    ? 'Your money has been refunded.'
                    : order.payment_status === 'paid' ||
                        order.payment_status === 'refund_pending' ||
                        order.payment_status === 'refund_failed'
                      ? 'Your refund is on its way back to the card you paid with. Banks usually take a few working days.'
                      : 'Nothing was charged.'}
                </p>
              </div>
            </div>
          ) : (
            <ol className="flex flex-col">
              {timeline.map((step, index) => {
                const done = index < currentIndex;
                const current = index === currentIndex;
                const pending = index > currentIndex;
                return (
                  <li key={step.status} className="flex gap-space-md">
                    <div className="flex flex-col items-center">
                      <span
                        className={`flex h-9 w-9 items-center justify-center rounded-full transition-colors ${
                          done || current
                            ? 'bg-primary text-on-primary'
                            : 'bg-surface-container text-on-surface-variant'
                        }`}
                      >
                        <Icon name={done ? 'check' : step.icon} className="text-[18px]" />
                      </span>
                      {index < timeline.length - 1 && (
                        <span
                          className={`w-0.5 flex-1 ${done ? 'bg-primary' : 'bg-outline'}`}
                          style={{ minHeight: 28 }}
                        />
                      )}
                    </div>

                    <div className={`pb-space-lg ${pending ? 'opacity-45' : ''}`}>
                      <p
                        className={`text-label-lg ${current ? 'text-primary' : 'text-on-surface'}`}
                      >
                        {STATUS_LABEL[step.status]}
                      </p>
                      <p className="text-body-sm text-on-surface-variant">{step.blurb}</p>
                      {current && (
                        <p className="mt-space-xs text-label-md text-on-surface-variant">
                          Updated {timeOfDay(order.updated_at)}
                        </p>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}

          {/* Cancelling is the stall's call now, not the customer's. A student
              who ordered at the wrong counter rings the stall, which is what
              the number below is for - and the stall can still refuse it, which
              refunds. */}
          {order.status === 'placed' && (
            <p className="mt-space-sm text-body-sm text-on-surface-variant">
              Need to change something? Call the stall before they start cooking.
            </p>
          )}
        </div>

        {/* Items */}
        <aside className="card flex h-fit flex-col gap-space-md p-space-md">
          <h2 className="flex items-center gap-space-xs text-headline-sm text-on-surface">
            <Icon name="receipt_long" className="text-[20px] text-primary" />
            {order.items.length} {order.items.length === 1 ? 'item' : 'items'}
          </h2>

          <ul className="flex flex-col gap-space-sm">
            {order.items.map((item) => (
              <li key={item.id} className="flex items-start justify-between gap-space-sm">
                <span className="flex min-w-0 gap-space-sm">
                  <span className="text-label-md text-primary">{item.quantity}×</span>
                  <span className="truncate text-body-sm text-on-surface">
                    {item.name_snapshot}
                    {/* Snapshotted at order time, so a reprint shows the size
                        that was actually bought even if the stall has since
                        renamed or removed it. */}
                    {item.variant_name_snapshot && (
                      <span className="text-on-surface-variant">
                        {' '}
                        · {item.variant_name_snapshot}
                      </span>
                    )}
                  </span>
                </span>
                <span className="shrink-0 text-label-md text-on-surface">
                  {rupees(Number.parseFloat(item.price_snapshot) * item.quantity)}
                </span>
              </li>
            ))}
          </ul>

          {/* The handover code. Shown from the moment the order is placed rather
              than only when a rider is on the way, so it is already on screen
              when somebody knocks - hunting for it one-handed at a door with
              food going cold is the thing to avoid. */}
          {order.fulfilment_type === 'delivery' &&
            order.delivery_code &&
            isActive(order.status) && (
              <div className="rounded-lg border-[1.5px] border-primary bg-primary-tint/40 p-space-md text-center">
                <p className="text-label-sm uppercase tracking-wide text-on-surface-variant">
                  Give this to whoever delivers
                </p>
                <p className="py-space-xs text-[32px] font-bold leading-none tracking-[0.3em] text-primary">
                  {order.delivery_code}
                </p>
                <p className="text-body-sm text-on-surface-variant">
                  They need it to close the order, so don't share it until your food
                  is in your hands.
                </p>
              </div>
            )}

          {/* Who is bringing it, once the stall has said. This is the whole point
              of assignment from the customer's side: somebody to ring when they
              are outside the wrong hostel gate. */}
          {order.fulfilment_type === 'delivery' && order.rider_phone && (
            <div className="flex items-center gap-space-sm rounded-lg border-[1.5px] border-primary bg-primary-tint/40 px-space-sm py-space-sm">
              <Icon name="sports_motorsports" className="text-[22px] text-primary" />
              <div className="min-w-0 flex-1">
                <p className="text-label-sm uppercase tracking-wide text-on-surface-variant">
                  Your rider
                </p>
                <p className="truncate text-label-lg text-on-surface">
                  {order.rider_name ?? 'On the way'}
                </p>
              </div>
              <a
                href={`tel:${order.rider_phone}`}
                className="btn-primary shrink-0 px-space-md py-space-xs"
              >
                <Icon name="call" className="text-[18px]" />
                Call
              </a>
            </div>
          )}

          {order.fulfilment_type === 'delivery' && !order.rider_phone && (
            <p className="rounded bg-surface-container px-space-sm py-space-sm text-body-sm text-on-surface-variant">
              {order.self_delivery
                ? "The stall is bringing this one over themselves."
                : 'The stall will let you know who is bringing it.'}
            </p>
          )}

          {/* How this order is arriving. For a delivery the destination is the
              thing the customer most wants confirmed back to them. */}
          <div className="flex items-start gap-space-sm rounded bg-surface-container px-space-sm py-space-sm">
            <Icon
              name={order.fulfilment_type === 'delivery' ? 'delivery_dining' : 'restaurant'}
              className="text-[20px] text-primary"
            />
            <div className="min-w-0">
              <p className="text-label-sm uppercase tracking-wide text-on-surface-variant">
                {order.fulfilment_type === 'delivery' ? 'Delivery' : 'Dine in'}
              </p>
              <p className="text-body-sm text-on-surface-medium">
                {order.fulfilment_type === 'delivery'
                  ? (order.delivery_location_label ?? 'On campus')
                  : 'Collect from the stall counter'}
              </p>
            </div>
          </div>

          {order.note && (
            <div className="rounded bg-surface-container px-space-sm py-space-sm">
              <p className="text-label-sm uppercase tracking-wide text-on-surface-variant">
                Your note
              </p>
              <p className="text-body-sm text-on-surface-medium">{order.note}</p>
            </div>
          )}

          <div className="flex items-center justify-between border-t border-outline-variant pt-space-sm">
            <div>
              <p className="text-headline-sm text-on-surface">Total</p>
              <p className="text-label-md text-on-surface-variant">
                {paymentLabel(order.payment_status)}
              </p>
            </div>
            <span className="text-headline-md text-primary">{rupees(order.total_amount)}</span>
          </div>
        </aside>
      </div>
    </div>
  );
}
