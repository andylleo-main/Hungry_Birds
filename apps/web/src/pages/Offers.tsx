import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, api } from '../lib/api';
import { rupees } from '../lib/format';
import { EmptyState, ErrorRetry, Icon, PageLoader } from '../components/ui';
import type {
  CashbackEntry,
  CashbackSummary,
  CashbackWallet,
  Coupon,
} from '../lib/types';

/** A date a student can act on, rather than a timestamp. */
function on(iso: string) {
  return new Date(iso).toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'short',
  });
}

function daysUntil(iso: string) {
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
}

/** "A", "A and B", "A, B and C" — a list a person would read aloud. */
function listed(names: string[]): string {
  if (names.length <= 1) return names[0] ?? 'no stalls';
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

function Wallet({ wallet }: { wallet: CashbackWallet }) {
  const gourmet = wallet.kind === 'gourmet';
  const balance = Number(wallet.balance);
  const soon = wallet.expires_next ? daysUntil(wallet.expires_next) : null;

  return (
    <div className="card flex flex-col gap-space-sm p-space-md md:p-space-lg">
      <div className="flex items-center gap-space-sm">
        <span
          className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${
            gourmet ? 'bg-warning/15' : 'bg-primary-tint'
          }`}
        >
          <Icon
            name={gourmet ? 'restaurant' : 'storefront'}
            className={`text-[20px] ${gourmet ? 'text-warning' : 'text-primary'}`}
          />
        </span>
        <div className="min-w-0">
          <p className="text-label-lg text-on-surface">
            {gourmet ? 'Gourmet Kitchen cashback' : 'Campus stalls cashback'}
          </p>
          <p className="text-body-sm text-on-surface-variant">
            {wallet.percent}% back, up to {rupees(wallet.cap)} an order
          </p>
        </div>
      </div>

      <p className="text-headline-lg text-on-surface">{rupees(wallet.balance)}</p>

      {/* The rule that catches people out, said on the card rather than in a
          footnote: the two balances are not interchangeable. */}
      <p className="text-body-sm text-on-surface-variant">
        {balance > 0
          ? gourmet
            ? 'Spend it at Gourmet Kitchen — up to 60% of your cart there.'
            : 'Spend it at any other stall — up to 20% of your cart.'
          : gourmet
            ? 'Order from Gourmet Kitchen to start earning here.'
            : 'Order from any campus stall to start earning here.'}
      </p>

      {balance > 0 && wallet.expires_next && (
        <p
          className={`flex items-center gap-space-xs text-label-md ${
            soon !== null && soon <= 7 ? 'text-warning' : 'text-on-surface-variant'
          }`}
        >
          <Icon name="schedule" className="text-[16px]" />
          {soon !== null && soon <= 0
            ? 'Expiring today'
            : `Expires from ${on(wallet.expires_next)}`}
        </p>
      )}
    </div>
  );
}

function CouponCard({ coupon }: { coupon: Coupon }) {
  const off =
    coupon.discount_type === 'percent'
      ? `${Number(coupon.discount_value)}% off` +
        (coupon.max_discount ? ` up to ${rupees(coupon.max_discount)}` : '')
      : `${rupees(coupon.discount_value)} off`;

  return (
    <div className="card flex flex-col gap-space-sm p-space-md">
      <div className="flex items-center gap-space-sm">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary-tint">
          <Icon name="sell" className="text-[20px] text-primary" />
        </span>
        <div className="min-w-0">
          {/* An automatic code has nothing to type, so showing one would be
              telling somebody to do something that is already done. */}
          <p className="truncate text-label-lg text-on-surface">
            {coupon.automatic ? (
              'Applied automatically'
            ) : (
              <span className="font-mono">{coupon.code}</span>
            )}
          </p>
          <p className="text-body-sm text-on-surface-variant">{off}</p>
        </div>
      </div>

      <p className="text-body-sm text-on-surface-variant">
        {coupon.description ??
          (coupon.automatic
            ? 'Comes off your order without being typed.'
            : 'Type it at checkout to use it.')}
      </p>

      <p className="text-label-md text-on-surface-variant">
        {/* Named in full rather than counted. A student deciding where to eat
            needs to know which kitchens, and a card has the room a one-line
            admin row does not. */}
        {coupon.all_stalls ? 'At any stall' : `At ${listed(coupon.stall_names)}`}
        {Number(coupon.min_order_value) > 0
          ? ` · orders over ${rupees(coupon.min_order_value)}`
          : ''}
      </p>
    </div>
  );
}

function Movement({ entry }: { entry: CashbackEntry }) {
  const credit = Number(entry.amount) > 0;
  const label =
    entry.reason === 'earned'
      ? `Earned at ${entry.stall_name ?? 'a stall'}`
      : entry.reason === 'returned'
        ? `Returned — ${entry.stall_name ?? 'the stall'} couldn't make your order`
        : `Used at ${entry.stall_name ?? 'a stall'}`;

  return (
    <div className="flex items-center gap-space-md border-b border-outline-variant py-space-sm last:border-0">
      <Icon
        name={credit ? 'add_circle' : 'remove_circle'}
        className={`text-[20px] ${credit ? 'text-success' : 'text-on-surface-variant'}`}
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-body-md text-on-surface">{label}</p>
        <p className="text-label-md text-on-surface-variant">
          {on(entry.created_at)}
          {entry.order_number ? ` · ${entry.order_number}` : ''}
          {entry.kind === 'gourmet' ? ' · Gourmet' : ''}
        </p>
      </div>
      <span
        className={`shrink-0 text-label-lg ${credit ? 'text-success' : 'text-on-surface'}`}
      >
        {credit ? '+' : '−'}
        {rupees(Math.abs(Number(entry.amount)))}
      </span>
    </div>
  );
}

/**
 * What a student has to spend, and where it came from.
 *
 * The movements are shown alongside the balances rather than hidden behind
 * another tap, because a balance somebody cannot account for is the thing that
 * generates support messages - and because cashback that expires needs to be
 * explainable before it goes rather than afterwards.
 *
 * Coupons join this page once their design arrives.
 */
export default function Offers() {
  const [summary, setSummary] = useState<CashbackSummary | null>(null);
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const [balances, codes] = await Promise.all([
        api.cashback(),
        // Without a stall, so only the site-wide ones: a code pinned to one
        // stall cannot be judged without knowing the cart it would apply to.
        // Subtotal 0 for the same reason - this is a list of what exists, not a
        // quote against a basket that has not been built yet.
        api.availableCoupons(null, '0').catch(() => []),
      ]);
      setSummary(balances);
      setCoupons(codes);
    } catch (e) {
      setSummary(null);
      setError(
        e instanceof ApiError && e.status === 401
          ? 'Sign in to see your cashback.'
          : "Couldn't load your offers.",
      );
    }
  }

  useEffect(() => {
    void load();
  }, []);

  if (error) return <ErrorRetry message={error} onRetry={load} />;
  if (!summary) return <PageLoader />;

  const anything = summary.wallets.some((w) => Number(w.balance) > 0);

  return (
    <div className="mx-auto max-w-content px-margin-mobile py-space-lg md:px-margin md:py-space-xl">
      <div className="mb-space-lg flex flex-wrap items-end justify-between gap-space-md">
        <div>
          <h1 className="text-headline-lg text-on-surface">Offers</h1>
          <p className="text-body-md text-on-surface-variant">
            Cashback you have earned, and what it is worth where.
          </p>
        </div>

        {/* Only once there is something to report. "You have saved ₹0" is a
            worse greeting than none, and the empty-wallet card below already
            explains how any of this starts.

            Named as cashback rather than as savings on purpose: coupon
            discounts are not in this figure. */}
        {Number(summary.saved_so_far) > 0 && (
          <div className="text-right">
            <p className="text-headline-lg text-success">
              {rupees(summary.saved_so_far)}
            </p>
            <p className="text-label-md text-on-surface-variant">
              saved with cashback so far
            </p>
          </div>
        )}
      </div>

      <div className="mb-space-lg grid gap-space-md md:grid-cols-2">
        {summary.wallets.map((wallet) => (
          <Wallet key={wallet.kind} wallet={wallet} />
        ))}
      </div>

      {!anything && (
        <div className="mb-space-lg card flex flex-wrap items-center gap-space-md p-space-md">
          <Icon name="lightbulb" className="text-[22px] text-primary" />
          <p className="min-w-0 flex-1 text-body-md text-on-surface-variant">
            Cashback lands when your order is completed, and it is yours to spend on
            the next one.
          </p>
          <Link to="/" className="btn-primary h-10">
            Find something to eat
          </Link>
        </div>
      )}

      {coupons.length > 0 && (
        <>
          <h2 className="mb-space-sm text-headline-sm text-on-surface">Coupons</h2>
          <div className="mb-space-lg grid gap-space-md md:grid-cols-2">
            {coupons.map((c) => (
              <CouponCard key={c.code} coupon={c} />
            ))}
          </div>
        </>
      )}

      <h2 className="mb-space-sm text-headline-sm text-on-surface">History</h2>
      {summary.entries.length === 0 ? (
        <EmptyState
          icon="history"
          title="Nothing here yet"
          message="Every rupee of cashback you earn or spend shows up here, with the order it came from."
        />
      ) : (
        <div className="card px-space-md">
          {summary.entries.map((entry) => (
            <Movement key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}
