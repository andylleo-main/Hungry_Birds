import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import type { Vendor } from '../lib/types';
import StallCard from '../components/StallCard';
import { EmptyState, ErrorRetry, Icon, PageLoader } from '../components/ui';
import { useAuth } from '../state/AuthContext';

type Filter = 'all' | 'open';

const TICKER = ['Order ahead', 'Skip the queue', 'Dine in', 'Hostel delivery', 'Live tracking', 'Cashback on every order'];

function Hero({ firstName, query, setQuery }: { firstName?: string; query: string; setQuery: (q: string) => void }) {
  return (
    <section className="relative overflow-hidden bg-primary text-white" data-testid="discover-hero">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.08]"
        style={{ backgroundImage: 'radial-gradient(#fff 1.2px, transparent 1.2px)', backgroundSize: '22px 22px' }}
      />
      <div className="relative mx-auto grid max-w-content gap-space-lg px-margin-mobile pb-space-xl pt-space-xl md:px-margin lg:grid-cols-[1.4fr_1fr] lg:items-end">
        <div className="flex animate-rise flex-col gap-space-md">
          <span className="inline-flex w-fit items-center gap-space-xs rounded-full bg-white/15 px-space-sm py-space-xs text-label-sm uppercase tracking-[0.14em]">
            <Icon name="bolt" className="text-[16px]" />
            {firstName ? `Hey ${firstName}` : 'Hey there'}, what's for food?
          </span>
          <h1 className="max-w-3xl text-display-hero-mobile md:text-display-hero">
            Campus food,
            <br />
            <span className="text-on-surface">without the queue.</span>
          </h1>
          <p className="max-w-xl text-body-md text-white/85 md:text-body-lg">
            Order from any stall at BIT Mesra. The kitchen starts on it as soon as they accept, and
            you can follow it live until it's ready to eat or on its way to you.
          </p>
        </div>

        <div className="flex animate-rise flex-col gap-space-sm [animation-delay:120ms]">
          <label className="text-label-sm uppercase tracking-[0.14em] text-white/80" htmlFor="stall-search">
            Find a stall
          </label>
          <div className="flex items-center gap-space-xs rounded-full bg-white p-[6px] shadow-sheet">
            <Icon name="search" className="pl-space-sm text-[22px] text-primary" />
            <input
              id="stall-search"
              data-testid="discover-search-input"
              className="w-full bg-transparent px-space-xs text-body-md text-on-surface placeholder:text-on-surface-variant focus:outline-none"
              placeholder="Dosa, maggi, burgers..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {query && (
              <button
                type="button"
                data-testid="discover-search-clear"
                onClick={() => setQuery('')}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface-container text-on-surface-variant hover:text-primary"
                aria-label="Clear search"
              >
                <Icon name="close" className="text-[18px]" />
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="relative overflow-hidden border-t border-white/15 bg-primary-deep py-space-sm">
        <div className="flex w-max animate-marquee gap-space-xl whitespace-nowrap">
          {[...TICKER, ...TICKER, ...TICKER, ...TICKER].map((t, i) => (
            <span key={i} className="flex items-center gap-space-xl font-display text-label-lg uppercase tracking-[0.1em] text-white/90">
              {t}
              <Icon name="flutter_dash" className="text-[18px] text-white/50" />
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function Discover() {
  const { user } = useAuth();
  const [vendors, setVendors] = useState<Vendor[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<Filter>('all');

  async function load() {
    setError(null);
    setVendors(null);
    try {
      setVendors(await api.listVendors());
    } catch {
      setError("We couldn't load the stalls. Check your connection and try again.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const visible = useMemo(() => {
    if (!vendors) return [];
    const needle = query.trim().toLowerCase();
    return vendors
      .filter((v) => (filter === 'open' ? v.is_open : true))
      .filter(
        (v) =>
          !needle ||
          v.stall_name.toLowerCase().includes(needle) ||
          (v.description ?? '').toLowerCase().includes(needle),
      )
      .sort((a, b) => Number(b.is_open) - Number(a.is_open));
  }, [vendors, query, filter]);

  const openCount = vendors?.filter((v) => v.is_open).length ?? 0;

  return (
    <>
      <Hero firstName={user?.full_name?.split(' ')[0]} query={query} setQuery={setQuery} />

      <div className="page">
        <div className="mb-space-lg flex flex-wrap items-end justify-between gap-space-md">
          <div>
            <span className="eyebrow">
              <span className="h-2 w-2 animate-pulse rounded-full bg-success" />
              {vendors ? `${openCount} ${openCount === 1 ? 'stall is' : 'stalls are'} open right now` : 'Checking who is open'}
            </span>
            <h2 className="mt-space-xs text-headline-lg text-on-surface">Stalls on campus</h2>
            <p className="text-body-sm text-on-surface-variant">Pick one to see what's on today's menu.</p>
          </div>
          <div className="flex gap-space-xs" role="group" aria-label="Filter stalls">
            <button
              type="button"
              data-testid="discover-filter-all"
              onClick={() => setFilter('all')}
              className={`pill ${filter === 'all' ? 'pill-active' : ''}`}
            >
              All stalls
            </button>
            <button
              type="button"
              data-testid="discover-filter-open"
              onClick={() => setFilter('open')}
              className={`pill ${filter === 'open' ? 'pill-active' : ''}`}
            >
              <Icon name="schedule" className="text-[16px]" />
              Open now
            </button>
          </div>
        </div>

        {error ? (
          <ErrorRetry message={error} onRetry={load} />
        ) : !vendors ? (
          <PageLoader />
        ) : visible.length === 0 ? (
          <EmptyState
            icon="storefront"
            title={query ? 'No stall matches that' : 'No stalls yet'}
            message={
              query
                ? 'Try another search, or switch the filter back to all stalls.'
                : 'Stalls show up here as soon as an admin approves them.'
            }
          />
        ) : (
          <div className="grid grid-cols-1 gap-gutter sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="stall-grid">
            {visible.map((vendor, i) => (
              <StallCard key={vendor.id} vendor={vendor} index={i} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
