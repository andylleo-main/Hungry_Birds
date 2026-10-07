import { useState } from 'react';
import { ApiError } from '../../lib/api';
import { Icon, Spinner } from '../../components/ui';
import type {
  AdminCoupon,
  AdminCouponInput,
  CouponAudience,
  DiscountType,
  ExpiryType,
  Vendor,
} from '../../lib/types';

/** `datetime-local` wants `YYYY-MM-DDTHH:mm` in local time, not an ISO string. */
function toLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const AUDIENCES: { value: CouponAudience; label: string; blurb: string }[] = [
  {
    value: 'anyone',
    label: 'Anyone with the code',
    blurb: 'Typed at checkout by whoever has it.',
  },
  {
    value: 'first_order',
    label: 'First order only',
    blurb: 'Refused once a student has completed an order.',
  },
  {
    value: 'named',
    label: 'Specific customers',
    blurb: 'Only the addresses you list below.',
  },
  {
    value: 'automatic',
    label: 'Everyone, applied automatically',
    blurb: 'No code to type — it applies itself to every eligible order.',
  },
];

/**
 * The create/edit form.
 *
 * Validated by the server, which is the authority; this only shapes the payload
 * and reflects the refusal. Two fields hide rather than being greyed: a max
 * discount on a flat coupon is a contradiction rather than an unavailable
 * option, and the unused half of the expiry pair is not a setting at all.
 */
export default function CouponForm({
  coupon,
  stalls,
  onCancel,
  onSave,
}: {
  coupon: AdminCoupon | null;
  stalls: Vendor[];
  onCancel: () => void;
  onSave: (body: AdminCouponInput) => Promise<void>;
}) {
  const [code, setCode] = useState(coupon?.code ?? '');
  // Defaults to every stall on a new coupon, matching the server's own default
  // and the common case.
  const [allStalls, setAllStalls] = useState(coupon?.all_stalls ?? true);
  const [vendorIds, setVendorIds] = useState<string[]>(coupon?.vendor_ids ?? []);
  const [discountType, setDiscountType] = useState<DiscountType>(
    coupon?.discount_type ?? 'percent',
  );
  const [discountValue, setDiscountValue] = useState(coupon?.discount_value ?? '10');
  const [maxDiscount, setMaxDiscount] = useState(coupon?.max_discount ?? '');
  const [expiryType, setExpiryType] = useState<ExpiryType>(coupon?.expiry_type ?? 'count');
  const [maxUses, setMaxUses] = useState(String(coupon?.max_uses ?? 100));
  const [expiresAt, setExpiresAt] = useState(toLocalInput(coupon?.expires_at ?? null));
  const [minOrder, setMinOrder] = useState(coupon?.min_order_value ?? '0');
  const [audience, setAudience] = useState<CouponAudience>(coupon?.audience ?? 'anyone');
  const [emails, setEmails] = useState((coupon?.audience_emails ?? []).join('\n'));
  const [description, setDescription] = useState(coupon?.description ?? '');
  const [isActive, setIsActive] = useState(coupon?.is_active ?? true);
  const [onePerCustomer, setOnePerCustomer] = useState(coupon?.one_per_customer ?? true);
  const [showInOffers, setShowInOffers] = useState(coupon?.show_in_offers ?? false);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSave({
        code: code.trim(),
        all_stalls: allStalls,
        // Cleared rather than sent alongside "every stall", so the payload says
        // what it means and a set left behind by an earlier edit cannot come
        // back if somebody narrows the coupon again.
        vendor_ids: allStalls ? [] : vendorIds,
        discount_type: discountType,
        discount_value: discountValue,
        // Only meaningful on a percentage, and the server clears it anyway -
        // sent as null so the payload says what it means.
        max_discount: discountType === 'percent' && maxDiscount ? maxDiscount : null,
        expiry_type: expiryType,
        max_uses: expiryType === 'count' ? Number(maxUses) : null,
        // Back to an instant the server can read. The input is local time.
        expires_at:
          expiryType === 'date' && expiresAt ? new Date(expiresAt).toISOString() : null,
        min_order_value: minOrder || '0',
        audience,
        audience_emails:
          audience === 'named'
            ? emails
                .split(/[\n,]/)
                .map((x) => x.trim())
                .filter(Boolean)
            : [],
        description: description.trim() || null,
        is_active: isActive,
        one_per_customer: onePerCustomer,
        show_in_offers: showInOffers,
      });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Couldn't save that. Check the fields and try again.",
      );
      setSaving(false);
    }
  }

  const field = 'flex flex-col gap-space-xs';
  const label = 'text-label-md text-on-surface-medium';

  return (
    <form onSubmit={submit} className="flex flex-col gap-space-md">
      <label className={field}>
        <span className={label}>Code</span>
        <input
          className="field font-mono uppercase"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="WELCOME100"
          required
          maxLength={32}
        />
      </label>

      <div className="grid gap-space-md sm:grid-cols-2">
        <label className={field}>
          <span className={label}>Discount type</span>
          <select
            className="field"
            value={discountType}
            onChange={(e) => setDiscountType(e.target.value as DiscountType)}
          >
            <option value="percent">Percent (%)</option>
            <option value="flat">Flat (₹)</option>
          </select>
        </label>
        <label className={field}>
          <span className={label}>
            Discount value {discountType === 'percent' ? '(%)' : '(₹)'}
          </span>
          <input
            className="field"
            value={discountValue}
            onChange={(e) => setDiscountValue(e.target.value)}
            inputMode="decimal"
            required
          />
        </label>
      </div>

      <div className="grid gap-space-md sm:grid-cols-2">
        <label className={field}>
          <span className={label}>Expiry type</span>
          <select
            className="field"
            value={expiryType}
            onChange={(e) => setExpiryType(e.target.value as ExpiryType)}
          >
            <option value="count">Count-based (max uses)</option>
            <option value="date">Date</option>
          </select>
        </label>
        {expiryType === 'count' ? (
          <label className={field}>
            <span className={label}>Max uses</span>
            <input
              className="field"
              value={maxUses}
              onChange={(e) => setMaxUses(e.target.value)}
              inputMode="numeric"
              required
            />
          </label>
        ) : (
          <label className={field}>
            <span className={label}>Expires</span>
            <input
              type="datetime-local"
              className="field"
              value={expiresAt}
              onChange={(e) => setExpiresAt(e.target.value)}
              required
            />
          </label>
        )}
      </div>

      <div className="grid gap-space-md sm:grid-cols-2">
        <label className={field}>
          <span className={label}>Minimum order value (₹)</span>
          <input
            className="field"
            value={minOrder}
            onChange={(e) => setMinOrder(e.target.value)}
            inputMode="decimal"
          />
        </label>
        {/* Hidden rather than greyed on a flat coupon: "₹100 off, up to ₹50" is
            a contradiction, not an option that happens to be unavailable. */}
        {discountType === 'percent' && (
          <label className={field}>
            <span className={label}>Max discount (₹)</span>
            <input
              className="field"
              value={maxDiscount}
              onChange={(e) => setMaxDiscount(e.target.value)}
              inputMode="decimal"
              placeholder="No cap"
            />
          </label>
        )}
      </div>

      <div className={field}>
        <span className={label}>Where it works</span>
        {/* Two options rather than a dropdown with "Every stall" as its first
            entry, because the two are different kinds of answer: one is a scope,
            the other is a list. Asked explicitly so that unticking the last
            stall cannot read as "every stall" - that would widen a code meant
            for one kitchen to the whole campus, which is the direction this must
            never fail in. The server refuses the pair too.

            Stacked rather than side by side. This form is a sheet about 430px
            wide whatever the window is, and Tailwind's `sm:` reads the viewport
            rather than the container - so two columns here squeezed "Only the
            stalls I pick" onto four lines and pushed its blurb off the card. */}
        <div className="grid gap-space-sm">
          {([
            {
              every: true,
              title: 'Every stall',
              blurb: 'Good anywhere on campus.',
              icon: 'public',
            },
            {
              every: false,
              title: 'Only the stalls I pick',
              blurb: 'Refused everywhere else.',
              icon: 'storefront',
            },
          ] as const).map((option) => {
            const selected = allStalls === option.every;
            return (
              <button
                key={option.title}
                type="button"
                aria-pressed={selected}
                onClick={() => setAllStalls(option.every)}
                className={`flex items-start gap-space-sm rounded-lg border-[1.5px] p-space-md text-left transition-colors ${
                  selected
                    ? 'border-primary bg-primary-tint/40'
                    : 'border-outline-variant bg-surface-container hover:bg-surface-container-high'
                }`}
              >
                <Icon
                  name={selected ? 'check_circle' : option.icon}
                  className={`text-[22px] ${
                    selected ? 'text-primary' : 'text-on-surface-variant'
                  }`}
                />
                <span className="min-w-0">
                  <span className="block text-label-lg text-on-surface">
                    {option.title}
                  </span>
                  <span className="block text-body-sm text-on-surface-variant">
                    {option.blurb}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        {!allStalls && (
          <div className="mt-space-xs flex max-h-64 flex-col gap-space-xs overflow-y-auto rounded border-[1.5px] border-outline-variant p-space-sm">
            {stalls.length === 0 ? (
              <p className="text-body-sm text-on-surface-variant">
                No approved stalls yet.
              </p>
            ) : (
              stalls.map((s) => (
                <label key={s.id} className="flex items-center gap-space-sm">
                  <input
                    type="checkbox"
                    checked={vendorIds.includes(s.id)}
                    onChange={(e) =>
                      setVendorIds((picked) =>
                        e.target.checked
                          ? [...picked, s.id]
                          : picked.filter((id) => id !== s.id),
                      )
                    }
                    className="h-4 w-4 accent-primary"
                  />
                  <span className="min-w-0 truncate text-body-md text-on-surface">
                    {s.stall_name}
                  </span>
                </label>
              ))
            )}
          </div>
        )}

        {!allStalls && (
          <span className="text-label-md text-on-surface-variant">
            {vendorIds.length === 0
              ? 'Pick at least one stall.'
              : `${vendorIds.length} stall${vendorIds.length === 1 ? '' : 's'} picked.`}
          </span>
        )}
      </div>

      <label className={field}>
        <span className={label}>Who can use it</span>
        <select
          className="field"
          value={audience}
          onChange={(e) => setAudience(e.target.value as CouponAudience)}
        >
          {AUDIENCES.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </select>
        <span className="text-label-md text-on-surface-variant">
          {AUDIENCES.find((a) => a.value === audience)?.blurb}
        </span>
      </label>

      {audience === 'named' && (
        <label className={field}>
          <span className={label}>Email addresses</span>
          <textarea
            className="min-h-[88px] w-full rounded bg-surface-container px-space-md py-space-sm text-body-md text-on-surface placeholder:text-on-surface-variant focus:bg-surface-container-lowest focus:outline-none focus:ring-[1.5px] focus:ring-primary"
            value={emails}
            onChange={(e) => setEmails(e.target.value)}
            placeholder={'one@bitmesra.ac.in\ntwo@bitmesra.ac.in'}
          />
          <span className="text-label-md text-on-surface-variant">
            One per line, or separated by commas.
          </span>
        </label>
      )}

      <label className={field}>
        <span className={label}>Description</span>
        <input
          className="field"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What this is for — students see it on their offers page"
          maxLength={255}
        />
      </label>

      <div className="flex flex-col gap-space-sm">
        {([
          [isActive, setIsActive, 'Active', 'Off keeps the code and its history but refuses it.'],
          [
            onePerCustomer,
            setOnePerCustomer,
            'One use per customer',
            'Off lets the same student use it again.',
          ],
          [
            showInOffers,
            setShowInOffers,
            "Show in customers' offers",
            'Off keeps it to whoever has the code.',
          ],
        ] as const).map(([value, set, text, blurb]) => (
          <label key={text} className="flex items-start gap-space-sm">
            <input
              type="checkbox"
              checked={value}
              onChange={(e) => set(e.target.checked)}
              className="mt-1 h-4 w-4 accent-primary"
            />
            <span className="min-w-0">
              <span className="block text-body-md text-on-surface">{text}</span>
              <span className="block text-label-md text-on-surface-variant">{blurb}</span>
            </span>
          </label>
        ))}
      </div>

      {error && (
        <p className="rounded bg-primary-tint px-space-sm py-space-sm text-body-sm text-primary">
          {error}
        </p>
      )}

      <div className="flex gap-space-sm">
        {/* The server refuses a narrowed coupon that names no stall with a 422.
            Disabled here so that refusal is never something a tap discovers -
            the line under the stall list already says what is missing. */}
        <button
          type="submit"
          className="btn-primary flex-1"
          disabled={saving || (!allStalls && vendorIds.length === 0)}
        >
          {saving ? <Spinner /> : 'Save coupon'}
        </button>
        <button type="button" className="btn-secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
      </div>
    </form>
  );
}
