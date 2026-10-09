import { rupees } from '../../lib/format';
import { Icon, QuantityStepper } from '../../components/ui';
import { keyOf, unitPrice } from '../../state/CartContext';
import { useCheckout } from '../../state/CheckoutContext';

/** A numbered block, as both checkout pages lay their questions out. */
export function Step({
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

/**
 * The basket.
 *
 * Editable on the review page, where changing the order is the point, and
 * read-only on the payment page, where it is a reminder rather than a control -
 * somebody about to pay should not discover they have nudged a stepper.
 */
export function OrderLines({ editable }: { editable: boolean }) {
  const { lines, soldOutKeys, setQuantity } = useCheckout();

  return (
    <ul className="flex flex-col gap-space-sm">
      {lines.map((line) => {
        // One lookup per line, and keyed on the line rather than the dish so a
        // sold-out Full does not cross out the Half beside it.
        const gone = soldOutKeys.has(keyOf(line));
        return (
          <li
            key={keyOf(line)}
            className={`flex items-start justify-between gap-space-sm rounded bg-surface-container px-space-sm py-space-sm ${
              gone ? 'opacity-60' : ''
            }`}
          >
            <div className="min-w-0">
              <p
                className={`truncate text-label-md ${
                  gone ? 'text-on-surface-variant line-through' : 'text-on-surface'
                }`}
              >
                {line.item.name}
                {line.variant && (
                  <span className="text-on-surface-variant"> · {line.variant.name}</span>
                )}
              </p>
              {gone ? (
                <p className="text-label-md text-on-surface-variant">Sold out</p>
              ) : (
                <p className="text-label-md text-primary">
                  {rupees(unitPrice(line) * line.quantity)}
                </p>
              )}
            </div>
            {editable ? (
              <QuantityStepper
                quantity={line.quantity}
                onChange={(next) => setQuantity(keyOf(line), next)}
                compact
              />
            ) : (
              <span className="shrink-0 text-label-md text-on-surface-variant">
                ×{line.quantity}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** Subtotal, the free-delivery line, any discount, and what is due. */
/** The one line about money coming back, under the total. */
export function PromoLine() {
  const { cashAtTheDoor, promo, applied, coupon, couponCredit, quote } = useCheckout();
  if (cashAtTheDoor) {
    return (
      <p className="flex items-center gap-space-xs rounded-md bg-surface-container px-space-sm py-space-xs text-label-md text-on-surface-variant" data-testid="promo-line-cod">
        <Icon name="info" className="text-[16px]" /> No offers or cashback on pay-on-delivery orders
      </p>
    );
  }
  const text =
    promo === 'cashback' && applied > 0
      ? `You're saving ${rupees(applied)} with your cashback`
      : promo === 'coupon' && coupon
        ? `You'll get ${rupees(couponCredit)} cashback from coupon ${coupon.code} once this order is completed`
        : promo === 'earn' && quote && Number(quote.earning) > 0
          ? `You'll earn ${rupees(quote.earning)} cashback on this order`
          : null;
  if (!text) return null;
  return (
    <p className="flex items-start gap-space-xs rounded-md bg-success/10 px-space-sm py-space-xs text-label-md text-success" data-testid="promo-line">
      <Icon name="redeem" className="mt-[1px] text-[16px]" /> {text}
    </p>
  );
}

export function Totals() {
  const { subtotal, fulfilment, applied, payable, cashAtTheDoor } = useCheckout();

  return (
    <>
      <div className="flex flex-col gap-space-xs border-t border-outline-variant pt-space-sm text-body-sm">
        <div className="flex justify-between text-on-surface-variant">
          <span>Items</span>
          <span className="text-on-surface">{rupees(subtotal)}</span>
        </div>
        <div className="flex justify-between text-on-surface-variant">
          <span>
            {fulfilment === null
              ? 'Delivery or pickup'
              : fulfilment === 'delivery'
                ? 'Delivery charge'
                : 'Pickup charge'}
          </span>
          <span className="text-success">Free</span>
        </div>
        {applied > 0 && (
          <div className="flex justify-between text-on-surface-variant">
            <span>Cashback used</span>
            <span className="text-success">−{rupees(applied)}</span>
          </div>
        )}
      </div>

      <div className="flex items-end justify-between border-t border-outline-variant pt-space-sm">
        <div>
          <p className="text-headline-sm text-on-surface">Total due</p>
          <p className="text-label-md text-on-surface-variant">
            {cashAtTheDoor ? 'Paid when it arrives' : 'Paid now, online'}
          </p>
        </div>
        <span className="block text-headline-lg text-primary" data-testid="checkout-total-due">{rupees(payable)}</span>
      </div>
      <PromoLine />
    </>
  );
}

/**
 * The things standing between this cart and an order.
 *
 * Shown on both pages, because either can be the one a customer is looking at
 * when a dish sells out under them - the menu is re-read once for the whole
 * checkout, and the answer can arrive on either screen.
 */
export function Obstacles() {
  const {
    soldOut,
    dropSoldOut,
    shortOfMinimum,
    minDelivery,
    stallName,
    dineInOk,
    error,
  } = useCheckout();

  return (
    <>
      {soldOut.length > 0 && (
        <div className="flex flex-col gap-space-sm rounded bg-warning-tint px-space-sm py-space-sm">
          <p className="text-body-sm text-on-surface">
            {soldOut.length === 1
              ? `${soldOut[0].item.name}${
                  soldOut[0].variant ? ` (${soldOut[0].variant.name})` : ''
                } is no longer available.`
              : 'Some items are no longer available.'}{' '}
            The stall has run out while your order was open.
          </p>
          <button type="button" className="btn-secondary w-full" onClick={dropSoldOut}>
            {soldOut.length === 1 ? 'Remove it and carry on' : 'Remove them and carry on'}
          </button>
        </div>
      )}

      {shortOfMinimum > 0 && soldOut.length === 0 && (
        <div className="rounded bg-warning-tint px-space-sm py-space-sm text-body-sm text-on-surface">
          <p>
            {stallName} delivers orders of {rupees(minDelivery)} or more. Add{' '}
            {rupees(shortOfMinimum)} more to have this delivered.
          </p>
          {dineInOk && (
            <p className="mt-space-xs text-on-surface-variant">
              Eating at the stall has no minimum.
            </p>
          )}
        </div>
      )}

      {error && soldOut.length === 0 && (
        <p className="rounded bg-primary-tint px-space-sm py-space-sm text-body-sm text-primary">
          {error}
        </p>
      )}
    </>
  );
}

/** The stall this order is from, as both pages head their content with. */
export function StallLine() {
  const { stallName, fulfilment, location, locations } = useCheckout();
  const where = locations?.find((l) => l.code === location)?.label;

  return (
    <div className="flex items-start gap-space-md rounded-lg bg-primary-tint/50 p-space-md">
      <Icon name="storefront" className="text-[24px] text-primary" />
      <div className="min-w-0">
        <p className="text-label-lg text-on-surface">{stallName}</p>
        <p className="text-body-sm text-on-surface-variant">
          {fulfilment === null
            ? 'Choose how you want it handed over'
            : fulfilment === 'delivery'
              ? where
                ? `Delivered to ${where}`
                : 'Delivered on campus'
              : 'Eat in or collect at the counter'}
        </p>
      </div>
    </div>
  );
}
