import { useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { rupees } from '../../lib/format';
import { Icon, Spinner } from '../../components/ui';
import { useCheckout } from '../../state/CheckoutContext';
import { Obstacles, OrderLines, StallLine, Step, Totals } from './parts';

/**
 * Page two: what comes off, how it is paid, and the one button that commits.
 *
 * Nothing on this page changes the order. The basket is here to be read, with a
 * way back to the page that can change it - somebody about to pay should not
 * discover they have nudged a stepper.
 *
 * Coupons will join this page when their design arrives; cashback is here
 * already, and the two belong together because they are the same question from
 * the customer's side: what can I take off this.
 */
export default function Payment() {
  const {
    count,
    fulfilment,
    payLater,
    setPayLater,
    cashAtTheDoor,
    quote,
    redeem,
    setRedeem,
    payable,
    placing,
    ready,
    blockedBecause,
    placeOrder,
    coupon,
    couponError,
    checkingCoupon,
    applyCoupon,
    clearCoupon,
  } = useCheckout();

  const [typed, setTyped] = useState('');

  async function submitCode(e: React.FormEvent) {
    e.preventDefault();
    if (await applyCoupon(typed)) setTyped('');
  }

  // Both promotions are offered, but only one can apply - the server refuses
  // the pair. Numbering the steps from what is actually on screen keeps "1, 2"
  // from becoming "1, 3" when a student has no cashback to spend.
  const offersCashback = quote !== null && Number(quote.redeemable) > 0;
  const payStep = offersCashback ? 3 : 2;

  // Reached directly - a refresh, or a pasted link. The cart survives in
  // localStorage but none of the answers do, so there is nothing to pay for
  // yet and the first page is where they get made.
  if (fulfilment === null) return <Navigate to="/checkout" replace />;

  return (
    <div className="grid gap-space-lg lg:grid-cols-[1fr_380px]">
      <div className="flex flex-col gap-space-md">
        {/* A reminder, not a control. The link is the way back to changing it. */}
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

        <Step index={1} title="Have a code?">
          {coupon ? (
            <div className="flex flex-wrap items-center gap-space-md rounded-lg border-[1.5px] border-primary bg-primary-tint/40 p-space-md">
              <Icon name="sell" className="text-[22px] text-primary" />
              <div className="min-w-0 flex-1">
                <p className="text-label-lg text-on-surface">
                  <span className="font-mono">{coupon.code}</span> &middot;{' '}
                  {rupees(coupon.discount)} off
                </p>
                <p className="text-body-sm text-on-surface-variant">
                  {coupon.description ??
                    (coupon.automatic
                      ? 'Applied automatically.'
                      : 'Applied to this order.')}
                </p>
              </div>
              <button type="button" onClick={clearCoupon} className="btn-ghost text-primary">
                Remove
              </button>
            </div>
          ) : (
            <form onSubmit={submitCode} className="flex flex-wrap gap-space-sm">
              <input
                className="field min-w-0 flex-1 font-mono uppercase"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder="Enter a code"
                maxLength={32}
                autoComplete="off"
                spellCheck={false}
              />
              <button
                type="submit"
                className="btn-secondary"
                disabled={checkingCoupon || !typed.trim()}
              >
                {checkingCoupon ? <Spinner /> : 'Apply'}
              </button>
            </form>
          )}

          {couponError && (
            <p className="mt-space-sm rounded bg-warning-tint px-space-sm py-space-sm text-body-sm text-on-surface">
              {couponError}
            </p>
          )}

          {/* Said before they try both, not after the server refuses it. */}
          {offersCashback && (
            <p className="mt-space-sm text-label-md text-on-surface-variant">
              A code or your cashback — one per order, whichever is worth more.
            </p>
          )}
        </Step>

        {/* Only when there is something to spend. A control offering nothing is
            a worse answer than no control: it reads as a feature that is broken
            rather than a balance that is empty, and the offers page is where an
            empty wallet gets explained. */}
        {offersCashback && quote && (
          <Step index={2} title="Cashback">
            <button
              type="button"
              aria-pressed={redeem}
              onClick={() => setRedeem(!redeem)}
              className={`flex w-full items-start gap-space-sm rounded-lg border-[1.5px] p-space-md text-left transition-colors ${
                redeem
                  ? 'border-primary bg-primary-tint/40'
                  : 'border-outline-variant bg-surface-container hover:bg-surface-container-high'
              }`}
            >
              <Icon
                name={redeem ? 'check_circle' : 'redeem'}
                className={`text-[22px] ${redeem ? 'text-primary' : 'text-on-surface-variant'}`}
              />
              <span className="min-w-0">
                <span className="block text-label-lg text-on-surface">
                  Use {rupees(quote.redeemable)}
                  {quote.kind === 'gourmet' ? ' Gourmet' : ''} cashback
                </span>
                <span className="block text-body-sm text-on-surface-variant">
                  {Number(quote.redeemable) < Number(quote.balance)
                    ? `You have ${rupees(quote.balance)} — up to ${quote.percent}% of a cart can be used.`
                    : `Your whole ${rupees(quote.balance)} balance.`}
                </span>
              </span>
            </button>
            {/* The rule worth saying before they commit, not after. */}
            {redeem && (
              <p className="mt-space-sm text-label-md text-on-surface-variant">
                This order won&apos;t earn cashback, since it&apos;s using some.
              </p>
            )}
            {coupon && (
              <p className="mt-space-sm text-label-md text-on-surface-variant">
                Using <span className="font-mono">{coupon.code}</span> instead.
                Ticking this drops the code.
              </p>
            )}
            <p className="mt-space-sm text-label-md text-on-surface-variant">
              <Link to="/offers" className="text-primary hover:underline">
                See all your cashback
              </Link>
            </p>
          </Step>
        )}

        <Step
          index={payStep}
          title="How you'll pay"
          aside={
            <span className="badge">
              <Icon name="lock" className="text-[12px]" />
              Secured by Razorpay
            </span>
          }
        >
          {fulfilment === 'delivery' ? (
            <div className="grid gap-space-sm sm:grid-cols-2">
              {([
                {
                  later: false,
                  label: 'Pay now',
                  blurb: 'Card, UPI or netbanking',
                  icon: 'credit_card',
                },
                {
                  later: true,
                  label: 'Pay on delivery',
                  blurb: 'Cash or UPI when it arrives',
                  icon: 'payments',
                },
              ] as const).map((option) => {
                const selected = payLater === option.later;
                return (
                  <button
                    key={option.label}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => setPayLater(option.later)}
                    className={`flex items-start gap-space-sm rounded-lg border-[1.5px] p-space-md text-left transition-colors ${
                      selected
                        ? 'border-primary bg-primary-tint/40'
                        : 'border-outline-variant bg-surface-container hover:bg-surface-container-high'
                    }`}
                  >
                    <Icon
                      name={option.icon}
                      className={`text-[22px] ${selected ? 'text-primary' : 'text-on-surface-variant'}`}
                    />
                    <span className="min-w-0">
                      <span className="block text-label-lg text-on-surface">{option.label}</span>
                      <span className="block text-body-sm text-on-surface-variant">
                        {option.blurb}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            /* Dine-in is prepaid, and there is no choice to offer: there is
               nobody to collect from somebody standing at the counter. Said
               rather than shown as a single selected option, which is what this
               step used to be - a question with one answer. */
            <p className="flex items-start gap-space-sm text-body-sm text-on-surface-variant">
              <Icon name="credit_card" className="mt-0.5 text-[18px] text-primary" />
              Paid online now, by UPI, card or net banking. The stall only sees your
              order once the payment goes through, so nothing is cooked until you have
              paid.
            </p>
          )}
        </Step>
      </div>

      <aside className="card sticky top-24 flex h-fit flex-col gap-space-md p-space-md">
        <div className="flex items-center justify-between">
          <h2 className="text-headline-sm text-on-surface">Payment</h2>
          <span className="badge">{count} items</span>
        </div>

        <Totals />

        <Obstacles />

        {/* Disabled on anything the server would refuse, so a tap is never spent
            discovering a rule. `ready` is the one source for that - the button
            and the handler used to carry different conditions, and a missing
            phone number was only found after a tap. */}
        <button
          type="button"
          className="btn-primary w-full"
          disabled={placing || !ready}
          onClick={placeOrder}
        >
          {placing ? (
            <Spinner />
          ) : !ready ? (
            'Something is missing'
          ) : cashAtTheDoor ? (
            <>
              Place order &middot; pay {rupees(payable)} on delivery
              <Icon name="arrow_forward" className="text-[18px]" />
            </>
          ) : (
            <>
              Pay {rupees(payable)}
              <Icon name="arrow_forward" className="text-[18px]" />
            </>
          )}
        </button>

        {/* The reason it is disabled, since the button itself cannot say it and
            the field that fixes it is on the page behind. */}
        {!ready && !placing && (
          <p className="text-center text-label-md text-on-surface-variant">
            {blockedBecause}
          </p>
        )}

        <p className="text-center text-label-md text-on-surface-variant">
          If the stall has run out and declines, you&apos;re refunded automatically.
        </p>
      </aside>
    </div>
  );
}
