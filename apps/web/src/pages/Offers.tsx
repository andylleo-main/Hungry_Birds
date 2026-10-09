import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, api } from '../lib/api';
import { rupees } from '../lib/format';
import { useCashbackConfig } from '../lib/cashback';
import { EmptyState, ErrorRetry, Icon, PageLoader } from '../components/ui';
import type { CashbackEntry, CashbackSummary, CashbackWallet, Coupon } from '../lib/types';

function on(iso: string) {
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}

function daysUntil(iso: string) {
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
}

/** "A", "A and B", "A, B and C". */
function listed(names: string[]): string {
  if (names.length <= 1) return names[0] ?? 'no stalls';
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

function Wallet({ wallet, gourmetName }: { wallet: CashbackWallet; gourmetName: string }) {
  const gourmet = wallet.kind === 'gourmet';
  const balance = Number(wallet.balance);
  const soon = wallet.expires_next ? daysUntil(wallet.expires_next) : null;
  const where = gourmet ? gourmetName || 'the Gourmet stall' : 'any other campus stall';

  return (
    <div
      data-testid={`wallet-${wallet.kind}`}
      className={`relative flex animate-rise flex-col gap-space-md overflow-hidden rounded-xl p-space-lg text-white ${
        gourmet ? 'bg-on-surface' : 'bg-primary'
      }`}
    >
      <div aria-hidden className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full border-[18px] border-white/10" />
      <div className="relative flex items-center justify-between gap-space-sm">
        <span className="text-label-sm uppercase tracking-[0.14em] text-white/75">
          {gourmet ? 'Gourmet wallet' : 'Campus wallet'}
        </span>
        <span className="rounded-full bg-white/15 px-space-sm py-[3px] text-label-sm">
          {wallet.percent}% back · up to {rupees(wallet.cap)}
        </span>
      </div>

      <div className="relative">
        <p className="font-display text-[52px] font-extrabold leading-none tracking-tight" data-testid={`wallet-${wallet.kind}-balance`}>
          {rupees(wallet.balance)}
        </p>
        <p className="mt-space-xs text-body-sm text-white/80">
          {balance > 0
            ? `Use it at ${where}. It can cover up to ${wallet.percent}% of your cart there.`
            : `Order from ${where} to start filling this wallet.`}
        </p>
      </div>

      <div className="relative flex flex-wrap items-center justify-between gap-space-sm border-t border-white/15 pt-space-md">
        {balance > 0 && wallet.expires_next ? (
          <span
            className={`flex items-center gap-space-xs text-label-md ${
              soon !== null && soon <= 7 ? 'text-[#FFD7A8]' : 'text-white/80'
            }`}
          >
            <Icon name="schedule" className="text-[16px]" />
            {soon !== null && soon <= 0
              ? 'Some of it expires today'
              : soon !== null && soon <= 7
                ? `Some of it expires in ${soon} ${soon === 1 ? 'day' : 'days'}`
                : `Next expiry ${on(wallet.expires_next)}`}
          </span>
        ) : (
          <span className="text-label-md text-white/70">Nothing expiring</span>
        )}
        <Link
          to="/"
          data-testid={`wallet-${wallet.kind}-spend`}
          className="inline-flex h-9 items-center gap-space-xs rounded-full bg-white px-space-md text-label-md text-on-surface transition-transform hover:scale-105"
        >
          {balance > 0 ? 'Spend it' : 'Order now'} <Icon name="arrow_forward" className="text-[16px]" />
        </Link>
      </div>
    </div>
  );
}

function CouponTicket({ coupon }: { coupon: Coupon }) {
  const [copied, setCopied] = useState(false);
  const headline =
    coupon.discount_type === 'percent'
      ? `${Number(coupon.discount_value)}% OFF`
      : `${rupees(coupon.discount_value)} OFF`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(coupon.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="flex animate-rise overflow-hidden rounded-lg border border-outline bg-white transition-shadow hover:shadow-card-hover" data-testid={`coupon-${coupon.code}`}>
      <div className="flex w-32 shrink-0 flex-col items-center justify-center gap-[2px] bg-primary px-space-sm py-space-md text-center text-white">
        <span className="font-display text-[26px] font-extrabold leading-none">{headline.split(' ')[0]}</span>
        <span className="text-label-sm uppercase tracking-[0.14em]">back</span>
        {coupon.max_discount && coupon.discount_type === 'percent' && (
          <span className="mt-space-xs text-[11px] text-white/80">up to {rupees(coupon.max_discount)}</span>
        )}
      </div>
      <div className="relative w-0 border-l-2 border-dashed border-outline" aria-hidden>
        <span className="absolute -left-[9px] -top-[9px] h-4 w-4 rounded-full border border-outline bg-surface" />
        <span className="absolute -bottom-[9px] -left-[9px] h-4 w-4 rounded-full border border-outline bg-surface" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-space-sm p-space-md">
        <p className="text-body-sm text-on-surface-medium">
          {coupon.description ??
            (coupon.automatic ? 'Pick it at checkout under "Apply a coupon".' : 'Enter this code at checkout.')}{' '}
          Its value comes back to you as cashback once the order is completed.
        </p>
        <p className="text-label-md text-on-surface-variant">
          {coupon.all_stalls ? 'Works at every stall' : `Only at ${listed(coupon.stall_names)}`}
          {Number(coupon.min_order_value) > 0 ? ` · on orders above ${rupees(coupon.min_order_value)}` : ''}
        </p>
        <div className="mt-auto">
          {coupon.automatic ? (
            <span className="badge bg-success/10 text-success">
              <Icon name="auto_awesome" className="text-[12px]" /> No code needed
            </span>
          ) : (
            <button
              type="button"
              onClick={() => void copy()}
              data-testid={`coupon-copy-${coupon.code}`}
              className="inline-flex h-9 items-center gap-space-sm rounded-full border-2 border-dashed border-primary/40 px-space-md font-mono text-label-lg tracking-[0.08em] text-primary transition-colors hover:bg-primary-tint"
            >
              {coupon.code}
              <Icon name={copied ? 'check' : 'content_copy'} className="text-[16px]" />
              <span className="sr-only">{copied ? 'Copied' : 'Copy code'}</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

type HistoryFilter = 'all' | 'earned' | 'coupon' | 'redeemed' | 'returned';

function Movement({ entry }: { entry: CashbackEntry }) {
  const credit = Number(entry.amount) > 0;
  const label =
    entry.reason === 'earned'
      ? `Earned at ${entry.stall_name ?? 'a stall'}`
      : entry.reason === 'coupon'
        ? `From coupon ${entry.coupon_code ?? ''} at ${entry.stall_name ?? 'a stall'}`
        : entry.reason === 'returned'
        ? `Given back: ${entry.stall_name ?? 'the stall'} couldn't make your order`
        : `Spent at ${entry.stall_name ?? 'a stall'}`;

  return (
    <div className="flex items-center gap-space-md border-b border-outline-variant py-space-md last:border-0" data-testid="cashback-entry">
      <span
        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-md ${
          credit ? 'bg-success/10 text-success' : 'bg-surface-container text-on-surface-variant'
        }`}
      >
        <Icon name={entry.reason === 'earned' ? 'south_west' : entry.reason === 'coupon' ? 'sell' : entry.reason === 'returned' ? 'undo' : 'north_east'} className="text-[20px]" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-label-lg text-on-surface">{label}</p>
        <p className="text-body-sm text-on-surface-variant">
          {on(entry.created_at)}
          {entry.order_number ? ` · #${entry.order_number}` : ''}
          {entry.kind === 'gourmet' ? ' · Gourmet wallet' : ' · Campus wallet'}
          {(entry.reason === 'earned' || entry.reason === 'coupon') && entry.expires_at ? ` · expires ${on(entry.expires_at)}` : ''}
        </p>
      </div>
      <span className={`shrink-0 font-display text-headline-sm ${credit ? 'text-success' : 'text-on-surface'}`}>
        {credit ? '+' : '−'}
        {rupees(Math.abs(Number(entry.amount)))}
      </span>
    </div>
  );
}

function HowItWorks({ normal, gourmet, gourmetName, expiry }: { normal: number; gourmet: number; gourmetName: string; expiry: number }) {
  const steps = [
    ['shopping_bag', 'Order and pay online', 'No offers or cashback on pay-on-delivery orders.'],
    ['task_alt', 'Get your food', `Once the order is completed, ${normal}% comes back to you${gourmetName ? `, or ${gourmet}% at ${gourmetName}` : ''}.`],
    ['redeem', 'Spend it next time', `Use it on your next order before it expires in ${expiry} days.`],
  ];
  return (
    <section className="mb-space-xl grid gap-space-md md:grid-cols-3" data-testid="cashback-how-it-works">
      {steps.map(([icon, title, body], i) => (
        <div key={title} className="flex gap-space-md rounded-lg border border-outline bg-surface-container/50 p-space-md">
          <span className="font-display text-[32px] font-extrabold leading-none text-primary/25">0{i + 1}</span>
          <div className="flex flex-col gap-[2px]">
            <span className="flex items-center gap-space-xs text-label-lg text-on-surface">
              <Icon name={icon} className="text-[18px] text-primary" /> {title}
            </span>
            <span className="text-body-sm text-on-surface-variant">{body}</span>
          </div>
        </div>
      ))}
    </section>
  );
}

export default function Offers() {
  const config = useCashbackConfig();
  const [summary, setSummary] = useState<CashbackSummary | null>(null);
  const [coupons, setCoupons] = useState<Coupon[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<HistoryFilter>('all');

  async function load() {
    setError(null);
    try {
      const [balances, codes] = await Promise.all([
        api.cashback(),
        // No stall and a zero subtotal: this lists what exists, not a quote.
        api.availableCoupons(null, '0').catch(() => []),
      ]);
      setSummary(balances);
      setCoupons(codes);
    } catch (e) {
      setSummary(null);
      setError(
        e instanceof ApiError && e.status === 401
          ? 'Sign in to see your cashback.'
          : "We couldn't load your offers. Please try again.",
      );
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const entries = useMemo(
    () => (summary?.entries ?? []).filter((e) => filter === 'all' || e.reason === filter),
    [summary, filter],
  );

  if (error) return <div className="page"><ErrorRetry message={error} onRetry={load} /></div>;
  if (!summary) return <PageLoader />;

  const total = summary.wallets.reduce((sum, w) => sum + Number(w.balance), 0);

  return (
    <div className="page" data-testid="offers-page">
      <div className="mb-space-xl flex flex-wrap items-end justify-between gap-space-lg">
        <div className="animate-rise">
          <span className="eyebrow"><Icon name="redeem" className="text-[16px]" /> Offers & cashback</span>
          <h1 className="mt-space-xs text-headline-lg text-on-surface md:text-[44px] md:leading-[48px]">
            You have <span className="text-primary" data-testid="offers-total-balance">{rupees(total)}</span> to spend
          </h1>
          <p className="mt-space-xs max-w-xl text-body-md text-on-surface-variant">
            Your cashback, the coupons you can use right now, and a record of every rupee in and out.
          </p>
        </div>
        {Number(summary.saved_so_far) > 0 && (
          <div className="rounded-lg border border-success/20 bg-success/5 px-space-lg py-space-md text-right" data-testid="offers-saved-so-far">
            <p className="font-display text-headline-lg text-success">{rupees(summary.saved_so_far)}</p>
            <p className="text-label-md text-on-surface-variant">saved with cashback so far</p>
          </div>
        )}
      </div>

      <div className="mb-space-lg grid gap-gutter md:grid-cols-2">
        {summary.wallets.map((wallet) => (
          <Wallet key={wallet.kind} wallet={wallet} gourmetName={config?.gourmet_stall_name ?? ''} />
        ))}
      </div>

      {config && (
        <HowItWorks
          normal={config.normal_percent}
          gourmet={config.gourmet_percent}
          gourmetName={config.gourmet_stall_name}
          expiry={config.expiry_days}
        />
      )}

      <section className="mb-space-xl">
        <div className="mb-space-md flex items-end justify-between">
          <div>
            <h2 className="text-headline-md text-on-surface">Coupons</h2>
            <p className="text-body-sm text-on-surface-variant" data-testid="coupon-rule">Coupons come back to you as cashback. Pay full price, and once the order is completed the coupon's value lands in your wallet. One offer per order, and none on pay-on-delivery orders.</p>
          </div>
        </div>
        {coupons.length === 0 ? (
          <EmptyState icon="sell" title="No coupons right now" message="New codes show up here when they go live. Keep an eye out around fests and exams." />
        ) : (
          <div className="grid gap-gutter md:grid-cols-2" data-testid="coupon-list">
            {coupons.map((c) => (
              <CouponTicket key={c.code} coupon={c} />
            ))}
          </div>
        )}
      </section>

      <section>
        <div className="mb-space-md flex flex-wrap items-end justify-between gap-space-sm">
          <h2 className="text-headline-md text-on-surface">Cashback history</h2>
          <div className="flex flex-wrap gap-space-xs" role="group" aria-label="Filter history">
            {(['all', 'earned', 'coupon', 'redeemed', 'returned'] as HistoryFilter[]).map((f) => (
              <button
                key={f}
                type="button"
                data-testid={`history-filter-${f}`}
                onClick={() => setFilter(f)}
                className={`pill ${filter === f ? 'pill-active' : ''}`}
              >
                {{ all: 'All', earned: 'Earned', coupon: 'From coupons', redeemed: 'Spent', returned: 'Given back' }[f]}
              </button>
            ))}
          </div>
        </div>
        {entries.length === 0 ? (
          <EmptyState
            icon="history"
            title={filter === 'all' ? 'No cashback yet' : 'Nothing here'}
            message={
              filter === 'all'
                ? 'Each rupee you earn or spend will show up here, with the order it came from.'
                : 'Nothing matches this filter yet.'
            }
            action={filter === 'all' ? <Link to="/" className="btn-primary mt-space-sm">Order something</Link> : undefined}
          />
        ) : (
          <div className="card px-space-md" data-testid="cashback-history">
            {entries.map((entry) => (
              <Movement key={entry.id} entry={entry} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
