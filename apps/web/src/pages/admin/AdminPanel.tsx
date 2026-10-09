import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../../lib/api';
import type { Vendor } from '../../lib/types';
import { EmptyState, ErrorRetry, Icon, PageLoader, Spinner } from '../../components/ui';
import Analytics from './Analytics';
import PriceChanges from './PriceChanges';
import Coupons from './Coupons';
import AdminOrders from './AdminOrders';
import AdminFinances from './AdminFinances';
import AdminPayouts from './AdminPayouts';
import { SectionHeading } from './parts';

type Tab = 'overview' | 'orders' | 'finances' | 'payouts' | 'stalls' | 'prices' | 'coupons';

function VendorRow({
  vendor,
  busy,
  onApprove,
  onSuspend,
  onFinances,
  onOrders,
}: {
  vendor: Vendor;
  busy: boolean;
  onApprove: () => void;
  onSuspend: () => void;
  onFinances: () => void;
  onOrders: () => void;
}) {
  return (
    <div className="card flex animate-rise flex-wrap items-center gap-space-md p-space-md" data-testid={`admin-stall-row-${vendor.id}`}>
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md bg-primary font-display text-headline-sm text-white">
        {vendor.stall_name.charAt(0)}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-space-sm">
          <p className="truncate text-label-lg text-on-surface">{vendor.stall_name}</p>
          {vendor.is_approved ? (
            <span className="badge bg-success/10 text-success">Approved</span>
          ) : (
            <span className="badge bg-warning/10 text-warning">Waiting for approval</span>
          )}
          {vendor.is_approved && (
            <span className={`badge ${vendor.is_open ? 'bg-success/10 text-success' : 'bg-surface-container text-on-surface-variant'}`}>
              {vendor.is_open ? 'Open' : 'Closed'}
            </span>
          )}
        </div>
        <p className="line-clamp-1 text-body-sm text-on-surface-variant">{vendor.description ?? 'No description yet.'}</p>
      </div>

      <div className="flex shrink-0 flex-wrap gap-space-xs">
        {busy ? (
          <Spinner className="text-primary" />
        ) : vendor.is_approved ? (
          <>
            <button type="button" className="btn-secondary h-10" onClick={onFinances} data-testid={`admin-stall-finances-${vendor.id}`}>
              <Icon name="account_balance" className="text-[18px]" /> Finances
            </button>
            <button type="button" className="btn-ghost h-10 border border-outline" onClick={onOrders} data-testid={`admin-stall-orders-${vendor.id}`}>
              <Icon name="receipt_long" className="text-[18px]" /> Orders
            </button>
            <button type="button" className="btn-ghost h-10 text-primary" onClick={onSuspend} data-testid={`admin-stall-suspend-${vendor.id}`}>
              Suspend
            </button>
          </>
        ) : (
          <button type="button" className="btn-primary h-10" onClick={onApprove} data-testid={`admin-stall-approve-${vendor.id}`}>
            <Icon name="check" className="text-[18px]" /> Approve
          </button>
        )}
      </div>
    </div>
  );
}

function Stalls({
  pending,
  approved,
  busyId,
  act,
  openFinances,
  openOrders,
}: {
  pending: Vendor[];
  approved: Vendor[];
  busyId: string | null;
  act: (v: Vendor, a: 'approve' | 'suspend') => void;
  openFinances: (id: string) => void;
  openOrders: (id: string) => void;
}) {
  const [view, setView] = useState<'pending' | 'approved'>(pending.length ? 'pending' : 'approved');
  const shown = view === 'pending' ? pending : approved;
  return (
    <div data-testid="admin-stalls">
      <SectionHeading
        eyebrow="Stalls"
        title="Stalls"
        subtitle="Approve new stalls, suspend ones that shouldn't be live, and jump to any stall's orders or finances."
        action={
          <div className="flex gap-space-xs">
            <button type="button" className={`pill ${view === 'pending' ? 'pill-active' : ''}`} onClick={() => setView('pending')} data-testid="admin-stalls-pending-tab">
              Waiting ({pending.length})
            </button>
            <button type="button" className={`pill ${view === 'approved' ? 'pill-active' : ''}`} onClick={() => setView('approved')} data-testid="admin-stalls-approved-tab">
              Approved ({approved.length})
            </button>
          </div>
        }
      />
      {shown.length === 0 ? (
        <EmptyState
          icon={view === 'pending' ? 'task_alt' : 'storefront'}
          title={view === 'pending' ? 'All caught up' : 'No approved stalls yet'}
          message={
            view === 'pending'
              ? "No stall is waiting for approval. New sign-ups from the merchant app will show up here."
              : 'Approve a stall and students can see it straight away.'
          }
        />
      ) : (
        <div className="flex flex-col gap-space-sm">
          {shown.map((vendor) => (
            <VendorRow
              key={vendor.id}
              vendor={vendor}
              busy={busyId === vendor.id}
              onApprove={() => act(vendor, 'approve')}
              onSuspend={() => act(vendor, 'suspend')}
              onFinances={() => openFinances(vendor.id)}
              onOrders={() => openOrders(vendor.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function AdminPanel() {
  const [vendors, setVendors] = useState<Vendor[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('overview');
  const [ordersVendor, setOrdersVendor] = useState('');
  const [financeVendor, setFinanceVendor] = useState('');
  const [priceCount, setPriceCount] = useState<number | null>(null);
  const [couponCount, setCouponCount] = useState<number | null>(null);

  async function load() {
    setError(null);
    setVendors(null);
    try {
      setVendors(await api.adminVendors(false));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? "This account isn't an admin." : "We couldn't load the stalls.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  // Switching section is a new page as far as the admin is concerned.
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, [tab]);

  async function act(vendor: Vendor, action: 'approve' | 'suspend') {
    setBusyId(vendor.id);
    setActionError(null);
    try {
      const updated = action === 'approve' ? await api.approveVendor(vendor.id) : await api.suspendVendor(vendor.id);
      setVendors((current) => (current ?? []).map((v) => (v.id === updated.id ? updated : v)));
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : `Couldn't ${action} ${vendor.stall_name}.`);
    } finally {
      setBusyId(null);
    }
  }

  const { pending, approved } = useMemo(() => {
    const all = vendors ?? [];
    return { pending: all.filter((v) => !v.is_approved), approved: all.filter((v) => v.is_approved) };
  }, [vendors]);

  const openFinances = (id: string) => {
    setFinanceVendor(id);
    setTab('finances');
  };
  const openOrders = (id: string) => {
    setOrdersVendor(id);
    setTab('orders');
  };

  const TABS: { id: Tab; label: string; icon: string; count?: number | null }[] = [
    { id: 'overview', label: 'Overview', icon: 'monitoring' },
    { id: 'orders', label: 'All orders', icon: 'receipt_long' },
    { id: 'finances', label: 'Finances', icon: 'account_balance' },
    { id: 'payouts', label: 'Weekly payouts', icon: 'handshake' },
    { id: 'stalls', label: 'Stalls', icon: 'storefront', count: pending.length || null },
    { id: 'prices', label: 'Price changes', icon: 'price_change', count: priceCount },
    { id: 'coupons', label: 'Coupons', icon: 'sell', count: couponCount },
  ];

  return (
    <div className="mx-auto max-w-content px-margin-mobile py-space-lg md:px-margin md:py-space-xl" data-testid="admin-panel">
      <div className="mb-space-lg flex flex-wrap items-center justify-between gap-space-md rounded-xl bg-primary p-space-lg text-white">
        <div className="flex items-center gap-space-md">
          <span className="flex h-12 w-12 items-center justify-center rounded-md bg-white text-primary">
            <Icon name="shield_person" className="text-[26px]" />
          </span>
          <div>
            <h1 className="font-display text-headline-lg">Admin panel</h1>
            <p className="text-body-sm text-white/80">Orders, money and stalls across all of Hungry Birds.</p>
          </div>
        </div>
        {vendors && (
          <div className="flex gap-space-lg text-right">
            <div><p className="font-display text-headline-md">{approved.length}</p><p className="text-label-sm uppercase text-white/70">Live stalls</p></div>
            <div><p className="font-display text-headline-md">{approved.filter((v) => v.is_open).length}</p><p className="text-label-sm uppercase text-white/70">Open now</p></div>
            <div><p className="font-display text-headline-md">{pending.length}</p><p className="text-label-sm uppercase text-white/70">Waiting</p></div>
          </div>
        )}
      </div>

      {error ? (
        <ErrorRetry message={error} onRetry={load} />
      ) : !vendors ? (
        <PageLoader />
      ) : (
        <div className="grid gap-space-lg lg:grid-cols-[220px_1fr]">
          <nav className="-mx-margin-mobile flex gap-space-xs overflow-x-auto px-margin-mobile pb-space-xs lg:sticky lg:top-24 lg:mx-0 lg:h-fit lg:flex-col lg:overflow-visible lg:px-0" data-testid="admin-nav">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                data-testid={`admin-tab-${t.id}`}
                onClick={() => setTab(t.id)}
                className={`flex shrink-0 items-center gap-space-sm rounded-md px-space-md py-[10px] text-left text-label-lg transition-colors duration-200 ${
                  tab === t.id ? 'bg-on-surface text-white' : 'text-on-surface-medium hover:bg-primary-tint hover:text-primary'
                }`}
              >
                <Icon name={t.icon} className="text-[20px]" />
                <span className="flex-1">{t.label}</span>
                {t.count ? (
                  <span className={`rounded-full px-[7px] text-label-sm ${tab === t.id ? 'bg-primary text-white' : 'bg-primary-tint text-primary'}`}>{t.count}</span>
                ) : null}
              </button>
            ))}
          </nav>

          <div className="min-w-0">
            {actionError && (
              <p className="mb-space-md rounded-md bg-primary-tint px-space-md py-space-sm text-body-sm text-primary" data-testid="admin-action-error">
                {actionError}
              </p>
            )}
            {tab === 'overview' ? (
              <>
                <SectionHeading eyebrow="Service-wide" title="Overview" subtitle="How Hungry Birds is doing across every stall." />
                <Analytics />
              </>
            ) : tab === 'orders' ? (
              <AdminOrders vendors={vendors} vendorId={ordersVendor} onVendorChange={setOrdersVendor} />
            ) : tab === 'finances' ? (
              <AdminFinances vendors={approved} vendorId={financeVendor} onSelect={setFinanceVendor} onViewOrders={openOrders} />
            ) : tab === 'payouts' ? (
              <AdminPayouts onOpenStall={openFinances} />
            ) : tab === 'stalls' ? (
              <Stalls pending={pending} approved={approved} busyId={busyId} act={act} openFinances={openFinances} openOrders={openOrders} />
            ) : tab === 'prices' ? (
              <>
                <SectionHeading eyebrow="Menus" title="Price changes" subtitle="Stalls can't change a price until you approve it." />
                <PriceChanges onCount={setPriceCount} />
              </>
            ) : (
              <>
                <SectionHeading eyebrow="Promotions" title="Coupons" subtitle="Create discount codes, choose which stalls they work at, and see who used them." />
                <Coupons onCount={setCouponCount} />
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
