import { useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../../lib/api';
import { rupees } from '../../lib/format';
import { EmptyState, ErrorRetry, Icon, PageLoader, Sheet, Spinner } from '../../components/ui';
import type {
  AdminCoupon,
  AdminCouponInput,
  CouponRedemption,
  Vendor,
} from '../../lib/types';
import CouponForm from './CouponForm';

function when(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/** What a coupon takes off, as a phrase rather than a pair of columns. */
function discountOf(c: AdminCoupon) {
  const base = c.discount_type === 'percent' ? `${Number(c.discount_value)}%` : rupees(c.discount_value);
  return c.discount_type === 'percent' && c.max_discount
    ? `${base} up to ${rupees(c.max_discount)}`
    : base;
}

function expiryOf(c: AdminCoupon) {
  if (c.expiry_type === 'count') return `Count: ${c.max_uses ?? '—'}`;
  return c.expires_at
    ? `Until ${new Date(c.expires_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`
    : 'Dated';
}

/**
 * Where a code works, in a few words for a one-line row.
 *
 * Names up to two, then counts — three stall names is longer than the rest of
 * the row put together, and the form is where the full set belongs.
 *
 * "Nowhere" is a real state, not a defensive branch: a coupon narrowed to stalls
 * that have since been deleted keeps its choice and loses its list, and it works
 * nowhere rather than everywhere. Saying so is the whole point of showing it.
 */
function whereItWorks(c: AdminCoupon): string {
  if (c.all_stalls) return 'Every stall';
  if (c.stall_names.length === 0) return 'No stalls left';
  if (c.stall_names.length <= 2) return c.stall_names.join(' and ');
  return `${c.stall_names.length} stalls`;
}

const AUDIENCE_LABEL: Record<AdminCoupon['audience'], string> = {
  anyone: 'Anyone with the code',
  first_order: 'First order only',
  named: 'Named customers',
  automatic: 'Everyone, applied automatically',
};

function CouponRow({
  coupon,
  busy,
  onEdit,
  onDelete,
}: {
  coupon: AdminCoupon;
  busy: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  // Only meaningful on a count-based coupon. A dated one has no denominator, so
  // a bar would be drawing a fraction of nothing.
  const capped = coupon.expiry_type === 'count' && coupon.max_uses;
  const pct = capped ? Math.min(100, Math.round((coupon.uses / coupon.max_uses!) * 100)) : null;

  return (
    <div className="card flex flex-wrap items-center gap-space-md p-space-md">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-space-sm">
          <p className="truncate font-mono text-label-lg text-on-surface">{coupon.code}</p>
          <span className="badge bg-primary-tint text-primary">{discountOf(coupon)}</span>
          {!coupon.is_active && (
            <span className="badge bg-surface-container text-on-surface-variant">Off</span>
          )}
          {coupon.audience === 'automatic' && (
            <span className="badge bg-warning/10 text-warning">Automatic</span>
          )}
          {coupon.show_in_offers && (
            <span className="badge bg-success/10 text-success">In offers</span>
          )}
        </div>
        <p className="truncate text-body-sm text-on-surface-variant">
          {expiryOf(coupon)} · {whereItWorks(coupon)} ·{' '}
          {AUDIENCE_LABEL[coupon.audience]}
          {Number(coupon.min_order_value) > 0
            ? ` · min ${rupees(coupon.min_order_value)}`
            : ''}
        </p>
      </div>

      <div className="w-32 shrink-0">
        <p className="text-right text-label-md text-on-surface">
          {coupon.uses}
          {capped ? ` / ${coupon.max_uses}` : ''}
        </p>
        {pct !== null && (
          <>
            <div className="mt-1 h-1.5 w-full rounded-full bg-surface-container">
              <div
                className="h-1.5 rounded-full bg-primary"
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="mt-1 text-right text-label-sm text-on-surface-variant">
              {pct}% used
            </p>
          </>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-space-sm">
        {busy ? (
          <Spinner />
        ) : (
          <>
            <button type="button" onClick={onEdit} className="btn-ghost text-primary">
              Edit
            </button>
            <button type="button" onClick={onDelete} className="btn-ghost text-primary">
              Delete
            </button>
          </>
        )}
      </div>
    </div>
  );
}

const STATE_STYLE: Record<CouponRedemption['state'], string> = {
  held: 'bg-warning/10 text-warning',
  consumed: 'bg-success/10 text-success',
  returned: 'bg-surface-container text-on-surface-variant',
};

/**
 * Discount codes, and the record of where each one went.
 *
 * The usage figure on every row is counted from the redemptions below it rather
 * than stored, so the two can never disagree - which is why there is no
 * "recount" button here to make them agree again.
 */
export default function Coupons({ onCount }: { onCount?: (n: number) => void }) {
  const [coupons, setCoupons] = useState<AdminCoupon[] | null>(null);
  const [log, setLog] = useState<CouponRedemption[]>([]);
  const [stalls, setStalls] = useState<Vendor[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editing, setEditing] = useState<AdminCoupon | 'new' | null>(null);

  async function load() {
    setError(null);
    try {
      const [rows, redemptions] = await Promise.all([
        api.adminCoupons(),
        api.couponRedemptions(),
      ]);
      setCoupons(rows);
      setLog(redemptions);
      onCount?.(rows.filter((c) => c.is_active).length);
    } catch (e) {
      setCoupons([]);
      setError(
        e instanceof ApiError && e.status === 403
          ? 'This account is not an admin.'
          : "Couldn't load the coupons.",
      );
    }
  }

  useEffect(() => {
    void load();
    // Loaded once on mount, like the lists beside it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The stalls a coupon can be pinned to. Only approved ones: a code for a stall
  // students cannot see would never be usable.
  useEffect(() => {
    let cancelled = false;
    api
      .adminVendors(false)
      .then((v) => {
        if (!cancelled) setStalls(v.filter((s) => s.is_approved));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  async function remove(coupon: AdminCoupon) {
    const used = coupon.uses > 0;
    const ok = window.confirm(
      used
        ? `${coupon.code} has been used ${coupon.uses} time${coupon.uses === 1 ? '' : 's'}. ` +
          'Deleting it removes that history too — switching it off keeps the record. Delete anyway?'
        : `Delete ${coupon.code}?`,
    );
    if (!ok) return;

    setBusyId(coupon.id);
    setActionError(null);
    try {
      await api.deleteCoupon(coupon.id);
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Couldn't delete that coupon.");
    } finally {
      setBusyId(null);
    }
  }

  async function handBack(row: CouponRedemption) {
    setBusyId(row.id);
    setActionError(null);
    try {
      await api.handBackRedemption(row.id);
      // Reloaded rather than patched in place: handing a use back changes the
      // coupon's count as well as this row, and the two must not drift apart on
      // screen any more than they do in the database.
      await load();
    } catch (e) {
      setActionError(
        e instanceof ApiError ? e.message : "Couldn't hand that use back.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function cleanUp() {
    setActionError(null);
    try {
      const { deleted } = await api.cleanUpExpiredCoupons();
      setActionError(
        deleted === 0
          ? 'Nothing had expired.'
          : `Removed ${deleted} expired coupon${deleted === 1 ? '' : 's'}.`,
      );
      await load();
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Couldn't clean up.");
    }
  }

  async function save(body: AdminCouponInput) {
    if (editing === null) return;
    if (editing === 'new') await api.createCoupon(body);
    else await api.updateCoupon(editing.id, body);
    setEditing(null);
    await load();
  }

  const expiredCount = useMemo(
    () =>
      (coupons ?? []).filter(
        (c) =>
          c.expiry_type === 'date' &&
          c.expires_at !== null &&
          new Date(c.expires_at) <= new Date(),
      ).length,
    [coupons],
  );

  if (coupons === null) return <PageLoader />;
  if (error && coupons.length === 0) return <ErrorRetry message={error} onRetry={load} />;

  return (
    <div>
      <div className="mb-space-md flex flex-wrap items-center justify-between gap-space-sm">
        <p className="text-body-sm text-on-surface-variant">
          {coupons.length} coupon{coupons.length === 1 ? '' : 's'}
        </p>
        <div className="flex flex-wrap items-center gap-space-sm">
          <button type="button" onClick={cleanUp} className="btn-ghost text-primary">
            Clean up expired ({expiredCount})
          </button>
          <button type="button" onClick={() => setEditing('new')} className="btn-primary h-10">
            <Icon name="add" className="text-[18px]" />
            New coupon
          </button>
        </div>
      </div>

      {actionError && (
        <p className="mb-space-md rounded bg-primary-tint px-space-md py-space-sm text-body-sm text-primary">
          {actionError}
        </p>
      )}

      {coupons.length === 0 ? (
        <EmptyState
          icon="sell"
          title="No coupons yet"
          message="Make one and students can type the code at checkout. Tick “show in offers” and it appears on their offers page too."
        />
      ) : (
        <div className="flex flex-col gap-space-sm">
          {coupons.map((coupon) => (
            <CouponRow
              key={coupon.id}
              coupon={coupon}
              busy={busyId === coupon.id}
              onEdit={() => setEditing(coupon)}
              onDelete={() => void remove(coupon)}
            />
          ))}
        </div>
      )}

      <h3 className="mb-space-sm mt-space-lg text-headline-sm text-on-surface">
        Redemptions
      </h3>
      {log.length === 0 ? (
        <EmptyState
          icon="history"
          title="Nothing used yet"
          message="Every use shows here: held while the order is open, consumed once it is finished, and returned if it was given back."
        />
      ) : (
        <div className="card flex flex-col px-space-md">
          {log.map((row) => (
            <div
              key={row.id}
              className="flex flex-wrap items-center gap-space-md border-b border-outline-variant py-space-sm last:border-0"
            >
              <span className="w-28 shrink-0 truncate font-mono text-label-md text-on-surface">
                {row.code}
              </span>
              <span className="min-w-0 flex-1 truncate text-body-sm text-on-surface-variant">
                {row.customer_email}
              </span>
              <span className="w-32 shrink-0 truncate font-mono text-label-md text-on-surface-variant">
                {row.order_number ?? '—'}
              </span>
              <span className="w-16 shrink-0 text-right text-label-md text-on-surface">
                {rupees(row.discount)}
              </span>
              <span className={`badge shrink-0 ${STATE_STYLE[row.state]}`}>{row.state}</span>
              <span className="w-40 shrink-0 text-right text-label-md text-on-surface-variant">
                {when(row.created_at)}
              </span>
              <span className="w-28 shrink-0 text-right">
                {row.state === 'returned' ? (
                  <span className="text-label-md text-on-surface-variant">Handed back</span>
                ) : busyId === row.id ? (
                  <Spinner />
                ) : (
                  <button
                    type="button"
                    onClick={() => void handBack(row)}
                    className="btn-ghost text-primary"
                  >
                    Hand back
                  </button>
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      {editing !== null && (
        <Sheet
          open
          onClose={() => setEditing(null)}
          title={editing === 'new' ? 'New coupon' : `Edit ${editing.code}`}
        >
          <CouponForm
            coupon={editing === 'new' ? null : editing}
            stalls={stalls}
            onCancel={() => setEditing(null)}
            onSave={save}
          />
        </Sheet>
      )}
    </div>
  );
}
