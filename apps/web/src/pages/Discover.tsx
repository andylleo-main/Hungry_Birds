import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';
import type { Vendor } from '../lib/types';
import StallCard from '../components/StallCard';
import { EmptyState, ErrorRetry, Icon, PageLoader } from '../components/ui';
import { useAuth } from '../state/AuthContext';

type Filter = 'all' | 'open';

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
      setError("Couldn't load the stalls. Check your connection.");
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
      // Open stalls first - a closed one is a dead end for the customer.
      .sort((a, b) => Number(b.is_open) - Number(a.is_open));
  }, [vendors, query, filter]);

  const openCount = vendors?.filter((v) => v.is_open).length ?? 0;
  const firstName = user?.full_name?.split(' ')[0];

  return (
    <div className="mx-auto max-w-content px-margin-mobile py-space-lg md:px-margin md:py-space-xl">
      {/* Hero */}
      <section className="relative mb-space-xl overflow-hidden rounded-xl bg-surface-container-lowest p-space-lg shadow-card md:p-space-xl">
        <div className="pointer-events-none absolute -right-20 -top-24 h-96 w-96 rounded-full bg-primary/5 blur-3xl" />
        <div className="relative z-10 flex flex-col gap-space-md">
          <span className="inline-flex w-fit items-center gap-space-xs rounded-full bg-primary/10 px-space-sm py-space-xs text-label-sm uppercase tracking-wider text-primary">
            <Icon name="bolt" className="text-[18px]" />
            Order ahead, skip the queue
          </span>

          <h1 className="max-w-2xl text-display-hero-mobile tracking-tight text-on-surface md:text-display-hero">
            {firstName ? `Hungry, ${firstName}?` : 'Hungry?'}{' '}
            <span className="italic text-primary">Order before you walk over.</span>
          </h1>

          <p className="max-w-xl text-body-md text-on-surface-variant md:text-body-lg">
            Pay online and the stall starts cooking the moment they accept. You'll see it go
            from accepted to ready, then eat in or have it brought to you.
          </p>

          <div className="mt-space-xs flex max-w-xl items-center gap-space-xs rounded-full bg-surface-container p-space-xs">
            <span className="material-symbols-outlined pl-space-sm text-[22px] text-primary">
              search
            </span>
            <input
              className="w-full bg-transparent px-space-sm text-body-sm text-on-surface placeholder:text-on-surface-variant focus:outline-none"
              placeholder="Search stalls or dishes..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        </div>
      </section>

      {/* Filter bar */}
      <div className="mb-space-lg flex flex-wrap items-center gap-space-sm rounded-lg border border-outline-variant bg-surface-container-lowest px-space-md py-space-sm">
        <span className="text-label-sm uppercase tracking-wide text-on-surface-variant">
          Filters:
        </span>
        <button
          type="button"
          onClick={() => setFilter('all')}
          className={`pill ${filter === 'all' ? 'pill-active' : ''}`}
        >
          All stalls
        </button>
        <button
          type="button"
          onClick={() => setFilter('open')}
          className={`pill ${filter === 'open' ? 'pill-active' : ''}`}
        >
          <Icon name="schedule" className="text-[16px]" />
          Open now
        </button>
        {vendors && (
          <span className="ml-auto text-label-md text-on-surface-variant">
            {openCount} {openCount === 1 ? 'stall' : 'stalls'} open right now
          </span>
        )}
      </div>

      <div className="mb-space-md flex items-end justify-between">
        <div>
          <h2 className="text-headline-md text-on-surface">Stalls on campus</h2>
          <p className="text-body-sm text-on-surface-variant">
            Tap a stall to see today's menu.
          </p>
        </div>
      </div>

      {error ? (
        <ErrorRetry message={error} onRetry={load} />
      ) : !vendors ? (
        <PageLoader />
      ) : visible.length === 0 ? (
        <EmptyState
          icon="storefront"
          title={query ? 'Nothing matched that' : 'No stalls yet'}
          message={
            query
              ? 'Try a different search, or clear the filters.'
              : 'Once an admin approves the first stall, it shows up here.'
          }
        />
      ) : (
        <div className="grid grid-cols-1 gap-space-md sm:grid-cols-2 lg:grid-cols-4">
          {visible.map((vendor) => (
            <StallCard key={vendor.id} vendor={vendor} />
          ))}
        </div>
      )}
    </div>
  );
}
