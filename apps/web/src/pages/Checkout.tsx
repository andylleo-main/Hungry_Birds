import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, api } from '../lib/api';
import { rupees, validateIndianMobile } from '../lib/format';
import { EmptyState, Icon, QuantityStepper, Spinner } from '../components/ui';
import { useAuth } from '../state/AuthContext';
import { useCart } from '../state/CartContext';

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
      });

      clear();
      navigate(`/orders/${order.id}`, { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not place the order. Try again.');
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
          <Step index={1} title="Where you'll collect">
            <div className="flex items-start gap-space-md rounded-lg bg-primary-tint/50 p-space-md">
              <Icon name="storefront" className="text-[24px] text-primary" />
              <div>
                <p className="text-label-lg text-on-surface">{vendor.stall_name}</p>
                <p className="text-body-sm text-on-surface-variant">
                  Collect from the stall counter once it's marked ready. You'll get live updates as
                  it's being made.
                </p>
              </div>
            </div>
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
              The stall calls this number when your order is ready.
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
                COD only
              </span>
            }
          >
            <div className="flex items-center gap-space-md rounded-lg border-[1.5px] border-primary bg-primary-tint/40 p-space-md">
              <Icon name="payments" className="text-[24px] text-primary" />
              <div className="flex-1">
                <p className="text-label-lg text-on-surface">Cash on pickup</p>
                <p className="text-body-sm text-on-surface-variant">
                  Pay the stall directly when you collect. No online payment.
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
              <span>Pickup charge</span>
              <span className="text-success">Free</span>
            </div>
          </div>

          <div className="flex items-end justify-between border-t border-outline-variant pt-space-sm">
            <div>
              <p className="text-headline-sm text-on-surface">Total due</p>
              <p className="text-label-md text-on-surface-variant">Payable at the counter</p>
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
                Place order ({rupees(subtotal)})
                <Icon name="arrow_forward" className="text-[18px]" />
              </>
            )}
          </button>

          <p className="text-center text-label-md text-on-surface-variant">
            The stall can still decline if they've run out.
          </p>
        </aside>
      </div>
    </div>
  );
}
