import { useNavigate } from 'react-router-dom';
import { rupees, validateIndianMobile } from '../../lib/format';
import { Icon, Spinner } from '../../components/ui';
import { useCheckout } from '../../state/CheckoutContext';
import { Obstacles, OrderLines, StallLine, Step, Totals } from './parts';

/**
 * Page one: what is being ordered, how it is handed over, and who to reach.
 *
 * Everything on this page is about the order itself. Nothing here commits
 * anybody to anything - the money is entirely on the next page - which is what
 * makes "Continue" safe to press and why the basket is editable here and
 * nowhere else.
 */
export default function Review() {
  const navigate = useNavigate();
  const {
    count,
    fulfilment,
    setFulfilment,
    modes,
    location,
    setLocation,
    locations,
    name,
    setName,
    phone,
    setPhone,
    note,
    setNote,
    soldOut,
    shortOfMinimum,
    blockedBecause,
    setError,
    quote,
  } = useCheckout();

  /**
   * What cashback is worth on this basket, in one line, before anybody gets to
   * the page that asks about it.
   *
   * Either half is worth saying and the saving comes first, because money off
   * this order is the stronger reason to keep going. Both figures are the
   * server's; nothing here works out a rate.
   */
  const cashbackAhead = !quote
    ? null
    : Number(quote.redeemable) > 0
      ? `${rupees(quote.redeemable)} of your cashback can come off on the next page.`
      : Number(quote.earning) > 0
        ? `This order earns you ${rupees(quote.earning)} in cashback.`
        : null;

  /**
   * Only the obstacles this page can do anything about.
   *
   * A missing phone number stops the order, but stopping *this* button on it
   * would be unhelpful: the field is right there, and the payment page shows
   * the same message against a button that can actually be the last one. What
   * belongs here is a sold-out dish, an unanswered question, and a basket under
   * the stall's minimum - each of which is fixed on this page.
   */
  /**
   * What the button should say when it cannot be pressed.
   *
   * Null means it can. A disabled button reading "Continue to payment" is the
   * worst of both: it looks like the way forward and does nothing, with no clue
   * which of four things is missing. So the label names the next action instead.
   *
   * The order is the order of the work, not the order of the page: the basket
   * first, then how it is handed over, then where. A student told to pick a
   * hostel and *then* told the order is too small to deliver has been led on,
   * so the minimum is asked about before the location.
   */
  const needName = !name.trim();
  const needPhone = validateIndianMobile(phone) !== null;
  const todo =
    soldOut.length > 0
      ? 'Remove the sold-out items'
      : fulfilment === null
        ? 'Choose dine in or delivery'
        : shortOfMinimum > 0
          ? `Add ${rupees(shortOfMinimum)} to have this delivered`
          : fulfilment === 'delivery' && !location
            ? 'Choose where to deliver it'
            : needName && needPhone
              ? 'Add your name and phone number'
              : needName
                ? 'Add your name'
                : needPhone
                  ? phone.trim()
                    ? 'Enter a valid 10-digit phone number'
                    : 'Add your phone number'
                  : null;

  const cannotContinue = todo !== null;

  function onwards() {
    if (cannotContinue) {
      setError(blockedBecause);
      return;
    }
    setError(null);
    navigate('/checkout/payment');
  }

  return (
    <div className="grid gap-space-lg lg:grid-cols-[1fr_380px]">
      <div className="flex flex-col gap-space-md">
        <Step index={1} title="Your order">
          <div className="mb-space-md">
            <StallLine />
          </div>
          <OrderLines editable />
          <p className="mt-space-sm text-label-md text-on-surface-variant">
            Set a quantity to zero to remove a dish.
          </p>
        </Step>

        <Step index={2} title="Dine in or delivery?">
          {modes.length === 0 ? (
            <p className="rounded bg-primary-tint px-space-sm py-space-sm text-body-sm text-primary">
              This stall isn&apos;t taking orders right now.
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
                  This stall hasn&apos;t switched on any delivery locations yet.
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

        <Step index={3} title="Your contact details">
          <div className="grid gap-space-md sm:grid-cols-2">
            <label className="flex flex-col gap-space-xs">
              <span className="text-label-md text-on-surface-medium">Your name</span>
              <input
                className="field"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="ADD YOUR NAME"
                data-testid="checkout-name-input"
                autoComplete="name"
              />
            </label>
            <label className="flex flex-col gap-space-xs">
              <span className="text-label-md text-on-surface-medium">Phone number</span>
              <input
                className="field"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="**********"
                maxLength={14}
                data-testid="checkout-phone-input"
                inputMode="tel"
                autoComplete="tel"
              />
            </label>
          </div>
          <p className="mt-space-sm flex items-center gap-space-xs text-body-sm text-on-surface-variant">
            <Icon name="call" className="text-[16px] text-primary" />
            {fulfilment === null
              ? 'The stall calls this number if there is a problem with your order.'
              : fulfilment === 'delivery'
                ? 'Shared with whoever brings your order, so they can reach you.'
                : 'The stall calls this number when your food is ready.'}
          </p>
        </Step>

        <Step index={4} title="A note for the kitchen">
          <textarea
            className="min-h-[88px] w-full rounded bg-surface-container px-space-md py-space-sm text-body-md text-on-surface placeholder:text-on-surface-variant focus:bg-surface-container-lowest focus:outline-none focus:ring-[1.5px] focus:ring-primary"
            placeholder="Less spicy, no onion, extra chutney..."
            maxLength={500}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </Step>
      </div>

      <aside className="card sticky top-24 flex h-fit flex-col gap-space-md p-space-md">
        <div className="flex items-center justify-between">
          <h2 className="text-headline-sm text-on-surface">Summary</h2>
          <span className="badge">{count} items</span>
        </div>

        <Totals />

        {/* Said here because it is a reason to carry on, and page one is where
            somebody decides whether to. Nothing to choose yet - the choice is
            the payment page's, and offering it twice is how two screens come to
            disagree about what was picked. */}
        {cashbackAhead && (
          <p className="flex items-start gap-space-xs rounded bg-primary-tint/50 px-space-sm py-space-sm text-label-md text-on-surface">
            <Icon name="redeem" className="text-[16px] text-primary" />
            {cashbackAhead}
          </p>
        )}

        <Obstacles />

        <button
          type="button"
          className="btn-primary w-full"
          disabled={cannotContinue}
          onClick={onwards}
          data-testid="checkout-continue-button"
        >
          {todo ?? (
            <>
              Continue to pay
              <Icon name="arrow_forward" className="text-[18px]" />
            </>
          )}
        </button>

        <p className="text-center text-label-md text-on-surface-variant">
          You won't be charged until the next step.
        </p>
      </aside>
    </div>
  );
}
