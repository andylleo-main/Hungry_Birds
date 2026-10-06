import { useEffect, useState } from 'react';
import { ApiError, api } from '../../lib/api';
import type { PendingPriceChange, PriceChangeTarget } from '../../lib/api';
import { EmptyState, ErrorRetry, Icon, PageLoader, Spinner } from '../../components/ui';

/** A key that is unique across both id spaces. */
function keyOf(change: PendingPriceChange) {
  return `${change.target}:${change.target_id}`;
}

function rupees(amount: string) {
  // Formatted, never parsed into arithmetic: these are Decimals on the wire and
  // the only job here is to put them on screen.
  return `₹${amount.replace(/\.00$/, '')}`;
}

function whenRequested(iso: string | null) {
  if (!iso) return 'at an unknown time';
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days < 1) return 'today';
  if (days === 1) return 'yesterday';
  return `${days} days ago`;
}

function ChangeRow({
  change,
  busy,
  onApprove,
  onReject,
}: {
  change: PendingPriceChange;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const rising = change.pct_change > 0;

  return (
    <div className="card flex flex-wrap items-center gap-space-md p-space-md">
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary-tint">
        <Icon name="sell" className="text-[22px] text-primary" />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-space-sm">
          <p className="truncate text-label-lg text-on-surface">
            {change.item_name}
            {change.variant_name ? ` · ${change.variant_name}` : ''}
          </p>
          <span
            className={`badge ${
              rising ? 'bg-warning/10 text-warning' : 'bg-success/10 text-success'
            }`}
          >
            {rising ? '+' : ''}
            {Math.round(change.pct_change)}%
          </span>
        </div>
        <p className="truncate text-body-sm text-on-surface-variant">
          {change.stall_name} · asked {whenRequested(change.requested_at)}
        </p>
        <p className="mt-1 text-body-sm text-on-surface">
          <span className="line-through text-on-surface-variant">
            {rupees(change.current_price)}
          </span>
          {' → '}
          <span className="text-label-lg">{rupees(change.pending_price)}</span>
        </p>
      </div>

      <div className="flex shrink-0 items-center gap-space-sm">
        {busy ? (
          <Spinner />
        ) : (
          <>
            <button type="button" onClick={onReject} className="btn-ghost text-primary">
              Reject
            </button>
            <button type="button" onClick={onApprove} className="btn-primary h-10">
              Approve
            </button>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * Price changes a stall has asked for, waiting on somebody to decide.
 *
 * Until this screen existed the merchant half of the loop was complete - a stall
 * could request a new price and see it marked pending - and the admin half was
 * not, so every request sat forever. The backend was already finished and
 * tested; this is only the missing window onto it.
 */
export default function PriceChanges({ onCount }: { onCount?: (n: number) => void }) {
  const [changes, setChanges] = useState<PendingPriceChange[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const rows = await api.adminPriceChanges();
      setChanges(rows);
      onCount?.(rows.length);
    } catch (e) {
      setChanges([]);
      setError(
        e instanceof ApiError && e.status === 403
          ? 'This account is not an admin.'
          : 'Could not load the price changes.',
      );
    }
  }

  useEffect(() => {
    void load();
    // Loaded once on mount, like the vendor list beside it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function decide(change: PendingPriceChange, verb: 'approve' | 'reject') {
    setBusyKey(keyOf(change));
    setActionError(null);
    const call =
      verb === 'approve' ? api.approvePriceChange : api.rejectPriceChange;
    try {
      await call(change.target as PriceChangeTarget, change.target_id);
      // Dropped from the list rather than refetched: the response is the new
      // price, not the row, and the rest of the queue has not moved.
      setChanges((current) => {
        const next = (current ?? []).filter((c) => keyOf(c) !== keyOf(change));
        onCount?.(next.length);
        return next;
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // Somebody else decided it, or the stall withdrew it. The list is stale
        // rather than wrong, so reload instead of reporting a failure.
        setActionError('That one had already been decided. Refreshed the list.');
        await load();
      } else {
        setActionError(
          e instanceof ApiError ? e.message : 'Could not save that decision.',
        );
      }
    } finally {
      setBusyKey(null);
    }
  }

  if (changes === null) return <PageLoader />;
  if (error && changes.length === 0) return <ErrorRetry message={error} onRetry={load} />;

  return (
    <div>
      {actionError && (
        <p className="mb-space-md rounded bg-primary-tint px-space-md py-space-sm text-body-sm text-primary">
          {actionError}
        </p>
      )}

      {changes.length === 0 ? (
        <EmptyState
          icon="task_alt"
          title="No price changes waiting"
          message="When a stall asks to change a price, it appears here until you approve or reject it. The old price keeps selling until then."
        />
      ) : (
        <div className="flex flex-col gap-space-sm">
          {changes.map((change) => (
            <ChangeRow
              key={keyOf(change)}
              change={change}
              busy={busyKey === keyOf(change)}
              onApprove={() => void decide(change, 'approve')}
              onReject={() => void decide(change, 'reject')}
            />
          ))}
        </div>
      )}
    </div>
  );
}
