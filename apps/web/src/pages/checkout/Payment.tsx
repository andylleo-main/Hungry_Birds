import { useEffect, useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { api } from '../../lib/api';
import { rupees } from '../../lib/format';
import { useCashbackConfig } from '../../lib/cashback';
import type { Coupon } from '../../lib/types';
import { Icon, Spinner } from '../../components/ui';
import { useCheckout } from '../../state/CheckoutContext';
import type { Promo } from '../../state/CheckoutContext';
import { Obstacles, OrderLines, StallLine, Step, Totals } from './parts';

function OptionCard({
  selected,
  disabled,
  icon,
  label,
  blurb,
  onClick,
  testid,
}: {
  selected: boolean;
  disabled?: boolean;
  icon: string;
  label: string;
  blurb: string;
  onClick: () => void;
  testid: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={disabled}
      onClick={onClick}
      data-testid={testid}
      className={`flex items-start gap-space-sm rounded-lg border-[1.5px] p-space-md text-left transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-45 ${
        selected ? 'border-primary bg-primary-tint/50' : 'border-outline bg-white hover:border-primary/40'
      }`}
    >
      <Icon name={selected ? 'radio_button_checked' : icon} className={`text-[22px] ${selected ? 'text-primary' : 'text-on-surface-variant'}`} />
      <span className="min-w-0">
        <span className="block text-label-lg text-on-surface">{label}</span>
        <span className="block text-body-sm text-on-surface-variant">{blurb}</span>
      </span>
    </button>
  );
}

function PayStep() {
  const { fulfilment, payLater, setPayLater } = useCheckout();
  return (
    <Step
      index={1}
      title="How you'll pay"
      aside={
        <span className="badge">
          <Icon name="lock" className="text-[12px]" />
          Secured by Razorpay
        </span>
      }
    >
      {fulfilment === 'delivery' ? (
        <div className="grid gap-space-sm sm:grid-cols-2" role="radiogroup" aria-label="How you'll pay">
          <OptionCard selected={!payLater} icon="credit_card" label="Pay now" blurb="UPI, card or net banking" onClick={() => setPayLater(false)} testid="pay-option-online" />
          <OptionCard selected={payLater} icon="payments" label="Pay on delivery" blurb="Cash or UPI when it reaches you. No offers or cashback." onClick={() => setPayLater(true)} testid="pay-option-cod" />
        </div>
      ) : (
        <p className="flex items-start gap-space-sm text-body-sm text-on-surface-variant">
          <Icon name="credit_card" className="mt-0.5 text-[18px] text-primary" />
          Dine-in orders are paid online now, by UPI, card or net banking. The stall only sees your order once
          the payment goes through.
        </p>
      )}
    </Step>
  );
}

function CouponPicker() {
  const { vendorId, subtotal, coupon, couponCredit, couponError, checkingCoupon, applyCoupon, clearCoupon } = useCheckout();
  const [typed, setTyped] = useState('');
  const [offers, setOffers] = useState<Coupon[]>([]);

  useEffect(() => {
    if (!vendorId || subtotal <= 0) return;
    let cancelled = false;
    api
      .availableCoupons(vendorId, subtotal.toFixed(2))
      .then((found) => !cancelled && setOffers(found))
      .catch(() => !cancelled && setOffers([]));
    return () => {
      cancelled = true;
    };
  }, [vendorId, subtotal]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (await applyCoupon(typed)) setTyped('');
  }

  if (coupon) {
    return (
      <div className="flex flex-wrap items-center gap-space-md rounded-lg border-[1.5px] border-success/40 bg-success/5 p-space-md" data-testid="coupon-applied">
        <Icon name="sell" className="text-[22px] text-success" />
        <div className="min-w-0 flex-1">
          <p className="text-label-lg text-on-surface">
            <span className="font-mono">{coupon.code}</span> · {rupees(couponCredit)} back as cashback
          </p>
          <p className="text-body-sm text-on-surface-variant">You pay full price now. The credit lands in your wallet once the order is completed.</p>
        </div>
        <button type="button" onClick={clearCoupon} className="btn-ghost text-primary" data-testid="coupon-remove">
          Remove
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-space-sm">
      <form onSubmit={submit} className="flex flex-wrap gap-space-sm">
        <input
          className="field min-w-0 flex-1 font-mono uppercase"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder="Enter a code"
          maxLength={32}
          autoComplete="off"
          spellCheck={false}
          data-testid="coupon-code-input"
        />
        <button type="submit" className="btn-secondary" disabled={checkingCoupon || !typed.trim()} data-testid="coupon-apply-button">
          {checkingCoupon ? <Spinner /> : 'Apply'}
        </button>
      </form>
      {couponError && (
        <p className="rounded bg-warning-tint px-space-sm py-space-sm text-body-sm text-on-surface" data-testid="coupon-error">{couponError}</p>
      )}
      {offers.length > 0 && (
        <div className="flex flex-wrap gap-space-xs">
          {offers.map((c) => (
            <button
              key={c.code}
              type="button"
              onClick={() => void applyCoupon(c.code)}
              data-testid={`coupon-suggestion-${c.code}`}
              className="inline-flex items-center gap-space-xs rounded-full border border-dashed border-primary/50 px-space-sm py-[5px] font-mono text-label-md text-primary transition-colors hover:bg-primary-tint"
            >
              {c.automatic ? 'Offer' : c.code} · {rupees(c.discount)} back
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function PromoStep() {
  const { cashAtTheDoor, promo, setRedeem, coupon, clearCoupon, quote, promoDropped } = useCheckout();
  const config = useCashbackConfig();
  const [couponOpen, setCouponOpen] = useState(false);

  const earning = quote ? Number(quote.earning) : 0;
  const redeemable = quote ? Number(quote.redeemable) : 0;
  const percent = quote?.kind === 'gourmet' ? config?.gourmet_percent : config?.normal_percent;
  const selected: Promo = couponOpen && promo === 'earn' ? 'coupon' : promo;

  function choose(next: Promo) {
    setCouponOpen(next === 'coupon');
    if (next !== 'coupon' && coupon) clearCoupon();
    setRedeem(next === 'cashback');
  }

  return (
    <Step index={2} title="Pick one offer">
      {cashAtTheDoor && (
        <p className="mb-space-sm flex items-start gap-space-xs rounded-md bg-surface-container px-space-md py-space-sm text-body-sm text-on-surface-medium" data-testid="promo-cod-note">
          <Icon name="info" className="mt-[1px] text-[18px] text-on-surface-variant" />
          <span>
            No offers or cashback on pay-on-delivery orders.
            {promoDropped && ' The offer you picked was removed because you chose to pay on delivery.'}
          </span>
        </p>
      )}
      <div className="grid gap-space-sm md:grid-cols-3" role="radiogroup" aria-label="Pick one offer">
        <OptionCard
          selected={!cashAtTheDoor && selected === 'earn'}
          disabled={cashAtTheDoor}
          icon="redeem"
          label="Earn cashback"
          blurb={
            earning > 0
              ? `Pay full price, get ${rupees(earning)} back when it's completed.`
              : `Pay full price, get ${percent ?? 20}% back when it's completed.`
          }
          onClick={() => choose('earn')}
          testid="promo-option-earn"
        />
        <OptionCard
          selected={!cashAtTheDoor && selected === 'cashback'}
          disabled={cashAtTheDoor || redeemable <= 0}
          icon="savings"
          label="Use my cashback"
          blurb={
            redeemable > 0
              ? `Take ${rupees(redeemable)} off now. This order won't earn cashback.`
              : 'No cashback to spend at this stall yet.'
          }
          onClick={() => choose('cashback')}
          testid="promo-option-cashback"
        />
        <OptionCard
          selected={!cashAtTheDoor && selected === 'coupon'}
          disabled={cashAtTheDoor}
          icon="sell"
          label="Apply a coupon"
          blurb="Pay full price. The coupon's value comes back to you as cashback."
          onClick={() => choose('coupon')}
          testid="promo-option-coupon"
        />
      </div>
      {!cashAtTheDoor && selected === 'coupon' && (
        <div className="mt-space-md">
          <CouponPicker />
        </div>
      )}
      <p className="mt-space-sm text-label-md text-on-surface-variant">
        <Link to="/offers" className="text-primary hover:underline">See your cashback and coupons</Link>
      </p>
    </Step>
  );
}

/** Page two: how you pay, your one offer, and the button that commits. */
export default function Payment() {
  const { count, fulfilment, cashAtTheDoor, applied, payable, placing, ready, blockedBecause, placeOrder } = useCheckout();

  if (fulfilment === null) return <Navigate to="/checkout" replace />;

  return (
    <div className="grid gap-space-lg lg:grid-cols-[1fr_380px]">
      <div className="flex flex-col gap-space-md">
        <PayStep />
        <PromoStep />

        <section className="card p-space-md md:p-space-lg">
          <div className="mb-space-md flex items-center justify-between gap-space-sm">
            <h2 className="text-headline-sm text-on-surface">You&apos;re ordering</h2>
            <Link to="/checkout" className="btn-ghost h-9 text-primary">
              <Icon name="edit" className="text-[16px]" />
              Change
            </Link>
          </div>
          <div className="mb-space-md">
            <StallLine />
          </div>
          <OrderLines editable={false} />
        </section>
      </div>

      <aside className="card sticky top-24 flex h-fit flex-col gap-space-md p-space-md">
        <div className="flex items-center justify-between">
          <h2 className="text-headline-sm text-on-surface">Payment</h2>
          <span className="badge">{count} items</span>
        </div>

        <Totals />

        <Obstacles />

        <button type="button" className="btn-primary w-full" disabled={placing || !ready} onClick={placeOrder} data-testid="checkout-pay-button">
          {placing ? (
            <Spinner />
          ) : !ready ? (
            'Something is missing'
          ) : cashAtTheDoor ? (
            <>
              Place order · pay {rupees(payable)} on delivery
              <Icon name="arrow_forward" className="text-[18px]" />
            </>
          ) : (
            <>
              Pay {rupees(payable)}
              {applied > 0 && ` · save ${rupees(applied)}`}
              <Icon name="arrow_forward" className="text-[18px]" />
            </>
          )}
        </button>

        {!ready && !placing && <p className="text-center text-label-md text-on-surface-variant">{blockedBecause}</p>}

        <p className="text-center text-label-md text-on-surface-variant">
          If the stall can&apos;t make your order, you&apos;re refunded automatically.
        </p>
      </aside>
    </div>
  );
}
