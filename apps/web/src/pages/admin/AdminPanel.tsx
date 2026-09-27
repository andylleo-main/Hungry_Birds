import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../../lib/api';
import type { Vendor } from '../../lib/types';
import { EmptyState, ErrorRetry, Icon, PageLoader, Spinner } from '../../components/ui';

type Tab = 'pending' | 'approved';

function VendorRow({
  vendor,
  busy,
  onApprove,
  onSuspend,
}: {
  vendor: Vendor;
  busy: boolean;
  onApprove: () => void;
  onSuspend: () => void;
}) {
  return (
    <div className="card flex flex-wrap items-center gap-space-md p-space-md">
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary-tint">
        <Icon name="storefront" className="text-[22px] text-primary" />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-space-sm">
          <p className="truncate text-label-lg text-on-surface">{vendor.stall_name}</p>
          {vendor.is_approved ? (
            <span className="badge bg-success/10 text-success">Approved</span>
          ) : (
            <span className="badge bg-warning/10 text-warning">Awaiting approval</span>
          )}
          {vendor.is_approved && (
            <span
              className={`badge ${
                vendor.is_open
                  ? 'bg-success/10 text-success'
                  : 'bg-surface-container text-on-surface-variant'
              }`}
            >
              {vendor.is_open ? 'Open' : 'Closed'}
            </span>
          )}
        </div>
        <p className="line-clamp-1 text-body-sm text-on-surface-variant">
          {vendor.description ?? 'No description provided.'}
        </p>
      </div>

      <div className="flex shrink-0 gap-space-sm">
        {busy ? (
          <Spinner className="text-primary" />
        ) : vendor.is_approved ? (
          <button type="button" className="btn-ghost text-primary" onClick={onSuspend}>
            Suspend
          </button>
        ) : (
          <button type="button" className="btn-primary h-10" onClick={onApprove}>
            <Icon name="check" className="text-[18px]" />
            Approve
          </button>
        )}
      </div>
    </div>
  );
}

export default function AdminPanel() {
  const [vendors, setVendors] = useState<Vendor[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('pending');

  async function load() {
    setError(null);
    setVendors(null);
    try {
      setVendors(await api.adminVendors(false));
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? 'This account is not an admin.'
          : "Couldn't load stalls.",
      );
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function act(vendor: Vendor, action: 'approve' | 'suspend') {
    setBusyId(vendor.id);
    setActionError(null);
    try {
      const updated =
        action === 'approve'
          ? await api.approveVendor(vendor.id)
          : await api.suspendVendor(vendor.id);
      setVendors((current) =>
        (current ?? []).map((v) => (v.id === updated.id ? updated : v)),
      );
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : `Could not ${action} ${vendor.stall_name}.`,
      );
    } finally {
      setBusyId(null);
    }
  }

  const { pending, approved } = useMemo(() => {
    const all = vendors ?? [];
    return {
      pending: all.filter((v) => !v.is_approved),
      approved: all.filter((v) => v.is_approved),
    };
  }, [vendors]);

  const shown = tab === 'pending' ? pending : approved;

  return (
    <div className="mx-auto max-w-content px-margin-mobile py-space-lg md:px-margin md:py-space-xl">
      <div className="mb-space-lg flex items-center gap-space-md">
        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-primary text-on-primary">
          <Icon name="shield_person" className="text-[22px]" />
        </span>
        <div>
          <h1 className="text-headline-lg text-on-surface">Admin</h1>
          <p className="text-body-sm text-on-surface-variant">
            Approve stalls before they become visible to students.
          </p>
        </div>
      </div>

      {error ? (
        <ErrorRetry message={error} onRetry={load} />
      ) : !vendors ? (
        <PageLoader />
      ) : (
        <>
          <div className="mb-space-lg grid gap-space-md sm:grid-cols-3">
            {[
              ['pending_actions', 'Awaiting approval', pending.length],
              ['storefront', 'Approved stalls', approved.length],
              ['schedule', 'Open right now', approved.filter((v) => v.is_open).length],
            ].map(([icon, label, value]) => (
              <div key={label as string} className="card flex items-center gap-space-md p-space-md">
                <span className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-tint">
                  <Icon name={icon as string} className="text-[20px] text-primary" />
                </span>
                <div>
                  <p className="text-headline-md text-on-surface">{value as number}</p>
                  <p className="text-label-md text-on-surface-variant">{label as string}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="mb-space-md flex gap-space-sm">
            <button
              type="button"
              onClick={() => setTab('pending')}
              className={`pill ${tab === 'pending' ? 'pill-active' : ''}`}
            >
              Awaiting approval{pending.length > 0 ? ` (${pending.length})` : ''}
            </button>
            <button
              type="button"
              onClick={() => setTab('approved')}
              className={`pill ${tab === 'approved' ? 'pill-active' : ''}`}
            >
              Approved ({approved.length})
            </button>
          </div>

          {actionError && (
            <p className="mb-space-md rounded bg-primary-tint px-space-md py-space-sm text-body-sm text-primary">
              {actionError}
            </p>
          )}

          {shown.length === 0 ? (
            <EmptyState
              icon={tab === 'pending' ? 'task_alt' : 'storefront'}
              title={tab === 'pending' ? 'Nothing waiting' : 'No approved stalls yet'}
              message={
                tab === 'pending'
                  ? 'Every stall that has applied is approved. New applications land here.'
                  : 'Approve a stall and it becomes visible to students straight away.'
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
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
