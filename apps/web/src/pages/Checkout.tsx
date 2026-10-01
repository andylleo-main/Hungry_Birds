import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, api } from '../lib/api';
import { rupees, validateIndianMobile } from '../lib/format';
import { EmptyState, Icon, QuantityStepper, Spinner } from '../components/ui';
import { useAuth } from '../state/AuthContext';
import { useCart } from '../state/CartContext';
import type { DeliveryLocation, FulfilmentType } from '../lib/types';
import { load as loadCashfree } from '@cashfreepayments/cashfree-js';

function Step({
  index,
  title,
  children,
  aside,
}: {
  index: number;
  title: string;
  children: React.ReactNode;
  aside?: React.ReactNode;
}) {
  return (
    <section className="card p-space-md md:p-space-lg">
      <div className="mb-space-md flex items-center justify-between gap-space-sm">
        <div className="flex items-center gap-space-sm">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-label-md text-on-primary">
            {index}
          </span>
          <h2 className="text-headline-sm text-on-surface">{title}</h2>
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

export default function Checkout() {
  const { vendor, lines, subtotal, count, setQuantity, clear, isEmpty } = useCart();
  const { user, updateProfile } = useAuth();
  const navigate = useNavigate();

  const [name, setName] = useState(user?.full_name ?? '');
  const [phone, setPhone] = useState(user?.phone ?? '');
  const [note, setNote] = useState('');
  const [placing, setPlacing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The stall's fulfilment settings, re-read here rather than taken from the
  // cart. The cart survives a reload in localStorage, so by the time someone
  // reaches checkout the stall may have stopped delivering, or switched off the
  // hostel they were going to pick. This is the last moment before the order is
  // sent, so it is the right moment to ask.
  const [fulfilment, setFulfilment] = useState<FulfilmentType | null>(null);
  const [locations, setLocations] = useState<DeliveryLocation[] | null>(null);
  const [location, setLocation] = useState('');
  const [dineInOk, setDineInOk] = useState(vendor?.dine_in_enabled ?? true);
  const [deliveryOk, setDeliveryOk] = useState(vendor?.delivery_enabled ?? true);

  const vendorId = vendor?.id;

  useEffect(() => {
    if (!vendorId) return;
    let cancelled = false;
    api
      .vendorDetail(vendorId)
      .then((detail) => {
        if (cancelled) return;
        setDineInOk(detail.dine_in_enabled);
        setDeliveryOk(detail.delivery_enabled);
        setLocations(detail.delivery_locations);
        // Pick a mode the stall actually offers, so the page never opens on a
        // choice that cannot be submitted.
        setFulfilment((current) => current ?? (detail.dine_in_enabled ? 'dine_in' : 'delivery'));
      })
      .catch(() => {
        // Leave whatever the cart knew. Placing the order will still be checked
        // server-side, so a failed read here costs a clear error later rather
        // than a wrong order now.
        if (!cancelled) setLocations([]);
      });
    return () => {
      cancelled = true;
    };
  }, [vendorId]);

  const modes = useMemo(
    () =>
      [
        dineInOk ? ({ value: 'dine_in', label: 'Dine in', icon: 'restaurant', blurb: 'Eat at or collect from the stall' } as const) : null,
        deliveryOk ? ({ value: 'delivery', label: 'Delivery', icon: 'delivery_dining', blurb: 'Brought to you on campus' } as const) : null,
      ].filter((m): m is NonNullable<typeof m> => m !== null),
    [dineInOk, deliveryOk],
  );

  if (isEmpty || !vendor) {
    return (
      <div className="mx-auto max-w-content px-margin-mobile py-space-xl md:px-margin">
        <EmptyState
          icon="shopping_bag"
          title="Your order is empty"
          message="Pick a stall and add a few dishes, then come back here to place the order."
          action={
            <Link to="/" className="btn-primary mt-space-sm">
              Browse stalls
            </Link>
          }
        />
      </div>
    );
  }

  async function placeOrder() {
    const phoneError = validateIndianMobile(phone);
    if (!name.trim()) {
      setError('Enter your name so the stall knows who to call for.');
      return;
    }
    if (phoneError) {
      setError(phoneError);
      return;
    }
    if (!fulfilment) {
      setError('Choose whether you want to dine in or have it delivered.');
      return;
    }
    if (fulfilment === 'delivery' && !location) {
      setError('Choose where you want your order delivered.');
      return;
    }

    setPlacing(true);
    setError(null);
    try {
      // The backend refuses an order from a customer with no phone, so make
      // sure the profile is saved before placing it.
      if (name.trim() !== user?.full_name || phone.trim() !== user?.phone) {
        await updateProfile({ full_name: name.trim(), phone: phone.trim() });
      }

      const order = await api.placeOrder({
        vendor_id: vendor!.id,
        items: lines.map((l) => ({ menu_item_id: l.item.id, quantity: l.quantity })),
        note: note.trim() || undefined,
        fulfilment_type: fulfilment,
        // Sent only for a delivery: the server rejects a dine-in that carries
        // one rather than ignoring it, so a stray value is not harmless.
        delivery_location: fulfilment === 'delivery' ? location : undefined,
      });

      // The order exists but no stall has seen it yet - it is invisible until
      // the payment webhook lands. So the cart is cleared only now, and the
      // tracking page is where an unfinished payment can be picked back up.
      const session = await api.paymentSession(order.id);
      clear();

      const cashfree = await loadCashfree({ mode: session.mode as 'sandbox' | 'production' });
      // Takes only the session id. No amount is passed, because the SDK does not
      // accept one - which is what makes the figure impossible to tamper with
      // from the browser.
      await cashfree.checkout({
        paymentSessionId: session.payment_session_id,
        redirectTarget: '_modal',
      });

      // The modal has closed. That tells us nothing reliable about whether the
      // payment succeeded - only Cashfree's webhook does - so this just sends
      // them somewhere that shows the live answer.
      navigate(`/orders/${order.id}`, { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : 'Could not start the payment. Nothing was charged - please try again.',
      );
      setPlacing(false);
    }
  }

  return (
    <div className="mx-auto max-w-content px-margin-mobile py-space-lg md:px-margin md:py-space-xl">
      <div className="mb-space-lg flex items-center gap-space-md">
        <button
          type="button"
          onClick={() => navigate(-1)}
          aria-label="Go back"
          className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-container transition-colors hover:bg-surface-container-high"
        >
          <Icon name="arrow_back" className="text-[20px]" />
        </button>
        <div>
          <p className="text-label-sm uppercase tracking-wide text-primary">Checkout</p>
          <h1 className="text-headline-lg text-on-surface">Review &amp; confirm</h1>
        </div>
      </div>

      <div className="grid gap-space-lg lg:grid-cols-[1fr_380px]">
        <div className="flex flex-col gap-space-md">
          <Step index={1} title="How you'll get it">
            <div className="mb-space-md flex items-start gap-space-md rounded-lg bg-primary-tint/50 p-space-md">
              <Icon name="storefront" className="text-[24px] text-primary" />
              <div>
                <p className="text-label-lg text-on-surface">{vendor.stall_name}</p>
                <p className="text-body-sm text-on-surface-variant">
                  You'll get live updates as your order is being made.
                </p>
              </div>
            </div>

            {modes.length === 0 ? (
              <p className="rounded bg-primary-tint px-space-sm py-space-sm text-body-sm text-primary">
                This stall isn't taking orders right now. Try another stall.
              </p>
            ) : (
              <div className="grid gap-space-sm sm:grid-cols-2">
                {modes.map((mode) => {
                  const selected = fulfilment === mode.value;
                  return (
                    <button
                      key={mode.value}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => setFulfilment(mode.value)}
                      className={`flex items-start gap-space-sm rounded-lg border-[1.5px] p-space-md text-left transition-colors ${
                        selected
                          ? 'border-primary bg-primary-tint/40'
                          : 'border-outline-variant bg-surface-container hover:bg-surface-container-high'
                      }`}
                    >
                      <Icon
                        name={mode.icon}
                        className={`text-[22px] ${selected ? 'text-primary' : 'text-on-surface-variant'}`}
                      />
                      <span className="min-w-0">
                        <span className="block text-label-lg text-on-surface">{mode.label}</span>
                        <span className="block text-body-sm text-on-surface-variant">
                          {mode.blurb}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            )}

            {fulfilment === 'delivery' && (
              <div className="mt-space-md">
                {locations === null ? (
                  <Spinner />
                ) : locations.length === 0 ? (
                  <p className="rounded bg-primary-tint px-space-sm py-space-sm text-body-sm text-primary">
                    This stall hasn't switched on any delivery locations yet.
                  </p>
                ) : (
                  <label className="flex flex-col gap-space-xs">
                    <span className="text-label-md text-on-surface-medium">Deliver to</span>
                    <select
                      className="field"
                      value={location}
                      onChange={(e) => setLocation(e.target.value)}
                    >
                      <option value="">Choose a place…</option>
                      {locations.map((loc) => (
                        <option key={loc.code} value={loc.code}>
                          {loc.label}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
            )}
          </Step>

          <Step index={2} title="How the stall reaches you">
            <div className="grid gap-space-md sm:grid-cols-2">
              <label className="flex flex-col gap-space-xs">
                <span className="text-label-md text-on-surface-medium">Your name</span>
                <input
                  className="field"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="So they know who to call for"
                  autoComplete="name"
                />
              </label>
              <label className="flex flex-col gap-space-xs">
                <span className="text-label-md text-on-surface-medium">Phone number</span>
                <input
                  className="field"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="98765 43210"
                  inputMode="tel"
                  autoComplete="tel"
                />
              </label>
            </div>
            <p className="mt-space-sm flex items-center gap-space-xs text-body-sm text-on-surface-variant">
              <Icon name="call" className="text-[16px] text-primary" />
              {fulfilment === 'delivery'
                ? 'Shared with whoever brings your order, so they can reach you.'
                : 'The stall calls this number when your order is ready.'}
            </p>
          </Step>

          <Step index={3} title="Anything to tell the stall?">
            <textarea
              className="min-h-[88px] w-full rounded bg-surface-container px-space-md py-space-sm text-body-md text-on-surface placeholder:text-on-surface-variant focus:bg-surface-container-lowest focus:outline-none focus:ring-[1.5px] focus:ring-primary"
              placeholder="Less spicy, no onion, extra chutney..."
              maxLength={500}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </Step>

          <Step
            index={4}
            title="Payment"
            aside={
              <span className="badge">
                <Icon name="lock" className="text-[12px]" />
                Secured by Cashfree
              </span>
            }
          >
            <div className="flex items-center gap-space-md rounded-lg border-[1.5px] border-primary bg-primary-tint/40 p-space-md">
              <Icon name="credit_card" className="text-[24px] text-primary" />
              <div className="flex-1">
                <p className="text-label-lg text-on-surface">Pay online to confirm</p>
                <p className="text-body-sm text-on-surface-variant">
                  UPI, cards or net banking. The stall only sees your order once the
                  payment goes through, so nothing is cooked until you've paid.
                </p>
              </div>
              <Icon name="check_circle" className="text-[22px] text-primary" />
            </div>
          </Step>
        </div>

        {/* Order summary rail */}
        <aside className="card sticky top-24 flex h-fit flex-col gap-space-md p-space-md">
          <div className="flex items-center justify-between">
            <h2 className="text-headline-sm text-on-surface">Order summary</h2>
            <span className="badge">{count} items</span>
          </div>

          <ul className="flex flex-col gap-space-sm">
            {lines.map((line) => (
              <li
                key={line.item.id}
                className="flex items-start justify-between gap-space-sm rounded bg-surface-container px-space-sm py-space-sm"
              >
                <div className="min-w-0">
                  <p className="truncate text-label-md text-on-surface">{line.item.name}</p>
                  <p className="text-label-md text-primary">
                    {rupees(Number.parseFloat(line.item.price) * line.quantity)}
                  </p>
                </div>
                <QuantityStepper
                  quantity={line.quantity}
                  onChange={(next) => setQuantity(line.item.id, next)}
                  compact
                />
              </li>
            ))}
          </ul>

          <div className="flex flex-col gap-space-xs border-t border-outline-variant pt-space-sm text-body-sm">
            <div className="flex justify-between text-on-surface-variant">
              <span>Item subtotal</span>
              <span className="text-on-surface">{rupees(subtotal)}</span>
            </div>
            <div className="flex justify-between text-on-surface-variant">
              <span>{fulfilment === 'delivery' ? 'Delivery charge' : 'Pickup charge'}</span>
              <span className="text-success">Free</span>
            </div>
          </div>

          <div className="flex items-end justify-between border-t border-outline-variant pt-space-sm">
            <div>
              <p className="text-headline-sm text-on-surface">Total due</p>
              <p className="text-label-md text-on-surface-variant">Paid now, online</p>
            </div>
            <span className="text-headline-lg text-primary">{rupees(subtotal)}</span>
          </div>

          {error && (
            <p className="rounded bg-primary-tint px-space-sm py-space-sm text-body-sm text-primary">
              {error}
            </p>
          )}

          <button type="button" className="btn-primary w-full" disabled={placing} onClick={placeOrder}>
            {placing ? (
              <Spinner />
            ) : (
              <>
                Pay {rupees(subtotal)}
                <Icon name="arrow_forward" className="text-[18px]" />
              </>
            )}
          </button>

          <p className="text-center text-label-md text-on-surface-variant">
            If the stall has run out and declines, you're refunded automatically.
          </p>
        </aside>
      </div>
    </div>
  );
}
