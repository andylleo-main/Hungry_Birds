import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, api } from '../lib/api';
import { rupees } from '../lib/format';
import { EmptyState, ErrorRetry, Icon, PageLoader } from '../components/ui';
import type { CashbackEntry, CashbackSummary, CashbackWallet } from '../lib/types';

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
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      setSummary(await api.cashback());
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
      <div className="mb-space-lg">
        <h1 className="text-headline-lg text-on-surface">Offers</h1>
        <p className="text-body-md text-on-surface-variant">
          Cashback you have earned, and what it is worth where.
        </p>
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
