import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { api } from '../lib/api';
import type { CategoryWithItems, MenuItem, VendorDetail } from '../lib/types';
import { placeholderGradient, rupees } from '../lib/format';
import { EmptyState, ErrorRetry, Icon, PageLoader, QuantityStepper } from '../components/ui';
import { useCart } from '../state/CartContext';

function MenuItemRow({
  item,
  vendor,
  disabled,
}: {
  item: MenuItem;
  vendor: VendorDetail;
  disabled: boolean;
}) {
  const { add, setQuantity, quantityOf } = useCart();
  const quantity = quantityOf(item.id);
  const unavailable = !item.is_available;

  return (
    <div
      className={`card flex gap-space-md p-space-md transition-shadow ${
        unavailable ? 'opacity-60' : 'hover:shadow-card-hover'
      }`}
    >
      <div className="h-24 w-24 shrink-0 overflow-hidden rounded-md">
        {item.image_url ? (
          <img
            src={item.image_url}
            alt={item.name}
            loading="lazy"
            className="h-full w-full object-cover"
          />
        ) : (
          <div
            className={`flex h-full w-full items-center justify-center bg-gradient-to-br ${placeholderGradient(item.id)}`}
          >
            <Icon name="restaurant" className="text-[24px] text-primary/50" />
          </div>
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-space-xs">
        <div className="flex items-start justify-between gap-space-sm">
          <h4 className="text-headline-sm text-on-surface">{item.name}</h4>
          <span className="shrink-0 text-label-lg text-on-surface">{rupees(item.price)}</span>
        </div>

        {item.description && (
          <p className="line-clamp-2 max-w-[55ch] text-body-sm text-on-surface-variant">
            {item.description}
          </p>
        )}

        <div className="mt-auto flex items-center justify-between pt-space-xs">
          {unavailable ? (
            <span className="badge bg-surface-container text-on-surface-variant">Sold out</span>
          ) : (
            <span />
          )}

          {!unavailable &&
            (quantity > 0 ? (
              <QuantityStepper
                quantity={quantity}
                onChange={(next) => setQuantity(item.id, next)}
                compact
              />
            ) : (
              <button
                type="button"
                disabled={disabled}
                onClick={() => add(vendor, item)}
                title={disabled ? 'This stall is closed right now' : undefined}
                className="inline-flex h-9 items-center gap-space-xs rounded-full bg-primary px-space-md text-label-md text-on-primary transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Icon name="add" className="text-[16px]" />
                Add
              </button>
            ))}
        </div>
      </div>
    </div>
  );
}

/** Sticky order panel, mirroring the mockup's right-hand cart rail. */
function CartRail({ vendor }: { vendor: VendorDetail }) {
  const { lines, subtotal, count, setQuantity, clear, isEmpty } = useCart();
  const navigate = useNavigate();

  return (
    <aside className="card sticky top-24 flex flex-col gap-space-md p-space-md">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-space-xs text-headline-sm text-on-surface">
          <Icon name="shopping_bag" className="text-[20px] text-primary" />
          Your order
        </h3>
        {count > 0 && <span className="badge">{count} items</span>}
      </div>

      {isEmpty ? (
        <p className="py-space-md text-center text-body-sm text-on-surface-variant">
          Nothing added yet. Tap <span className="text-on-surface">Add</span> on any dish.
        </p>
      ) : (
        <>
          <ul className="flex flex-col gap-space-sm">
            {lines.map((line) => (
              <li
                key={line.item.id}
                className="flex items-start justify-between gap-space-sm rounded bg-surface-container px-space-sm py-space-sm"
              >
                <div className="min-w-0">
                  <p className="truncate text-label-md text-on-surface">{line.item.name}</p>
                  <p className="text-label-md text-primary">
                    {rupees(Number.parseFloat(line.item.price) * line.quantity)}
                  </p>
                </div>
                <QuantityStepper
                  quantity={line.quantity}
                  onChange={(next) => setQuantity(line.item.id, next)}
                  compact
                />
              </li>
            ))}
          </ul>

          <div className="flex flex-col gap-space-xs border-t border-outline-variant pt-space-sm text-body-sm">
            <div className="flex justify-between text-on-surface-variant">
              <span>Item subtotal</span>
              <span className="text-on-surface">{rupees(subtotal)}</span>
            </div>
            {/* No delivery fee, service charge or taxes: you collect at the
                counter and pay the stall directly. */}
            <div className="flex justify-between text-on-surface-variant">
              <span>Pickup</span>
              <span className="text-success">Free</span>
            </div>
          </div>

          <div className="flex items-center justify-between border-t border-outline-variant pt-space-sm">
            <span className="text-headline-sm text-on-surface">Total</span>
            <span className="text-headline-md text-primary">{rupees(subtotal)}</span>
          </div>

          <button
            type="button"
            className="btn-primary w-full"
            disabled={!vendor.is_open}
            onClick={() => navigate('/checkout')}
          >
            {vendor.is_open ? 'Review & place order' : 'Stall is closed'}
            {vendor.is_open && <Icon name="arrow_forward" className="text-[18px]" />}
          </button>

          <button type="button" className="btn-ghost w-full text-body-sm" onClick={clear}>
            Clear order
          </button>

          <p className="flex items-center justify-center gap-space-xs text-label-md text-on-surface-variant">
            <Icon name="payments" className="text-[16px] text-primary" />
            Pay cash when you collect
          </p>
        </>
      )}
    </aside>
  );
}

export default function Stall() {
  const { vendorId = '' } = useParams();
  const [vendor, setVendor] = useState<VendorDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<string | null>(null);

  async function load() {
    setError(null);
    setVendor(null);
    try {
      setVendor(await api.vendorDetail(vendorId));
    } catch {
      setError("Couldn't load this stall.");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vendorId]);

  const sections: CategoryWithItems[] = useMemo(() => {
    if (!vendor) return [];
    const withItems = vendor.categories.filter((c) => c.items.length > 0);
    if (vendor.uncategorized_items.length > 0) {
      withItems.push({
        id: '__other',
        name: 'More from this stall',
        sort_order: 999,
        items: vendor.uncategorized_items,
      });
    }
    return withItems;
  }, [vendor]);

  if (error) {
    return (
      <div className="mx-auto max-w-content px-margin-mobile py-space-xl md:px-margin">
        <ErrorRetry message={error} onRetry={load} />
      </div>
    );
  }
  if (!vendor) return <PageLoader />;

  const itemCount = sections.reduce((sum, s) => sum + s.items.length, 0);

  return (
    <div className="mx-auto max-w-content px-margin-mobile py-space-lg md:px-margin md:py-space-xl">
      <Link
        to="/"
        className="mb-space-md inline-flex items-center gap-space-xs text-label-md text-on-surface-variant hover:text-on-surface"
      >
        <Icon name="arrow_back" className="text-[18px]" />
        All stalls
      </Link>

      {/* Banner */}
      <div className="relative mb-space-lg overflow-hidden rounded-xl">
        <div className="h-44 w-full md:h-56">
          {vendor.cover_image_url ? (
            <img
              src={vendor.cover_image_url}
              alt={vendor.stall_name}
              className="h-full w-full object-cover"
            />
          ) : (
            <div
              className={`h-full w-full bg-gradient-to-br ${placeholderGradient(vendor.id)}`}
            />
          )}
        </div>
        <div className="absolute inset-0 bg-gradient-to-t from-black/55 via-black/10 to-transparent" />
        <div className="absolute bottom-space-md left-space-md right-space-md flex flex-wrap items-end justify-between gap-space-sm">
          <div className="min-w-0">
            <h1 className="truncate text-headline-lg text-white">{vendor.stall_name}</h1>
            {vendor.description && (
              <p className="line-clamp-1 max-w-xl text-body-sm text-white/85">
                {vendor.description}
              </p>
            )}
          </div>
          <span
            className={`inline-flex h-8 items-center gap-space-xs rounded-full px-space-md text-label-md ${
              vendor.is_open ? 'bg-success text-white' : 'bg-on-surface/85 text-white'
            }`}
          >
            <Icon name={vendor.is_open ? 'check_circle' : 'bedtime'} className="text-[16px]" />
            {vendor.is_open ? 'Open now' : 'Closed'}
          </span>
        </div>
      </div>

      {!vendor.is_open && (
        <div className="mb-space-lg flex items-center gap-space-sm rounded-lg bg-primary-tint px-space-md py-space-sm text-body-sm text-on-surface-medium">
          <Icon name="info" className="text-[20px] text-primary" />
          This stall isn't taking orders right now. You can still browse the menu.
        </div>
      )}

      {/* Info strip - the mockup's delivery time / fee / min order row,
          carrying what's actually true for campus pickup. */}
      <div className="mb-space-lg grid grid-cols-3 divide-x divide-outline-variant overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest">
        {[
          ['storefront', 'Collect at', 'The stall'],
          ['payments', 'Payment', 'Cash on pickup'],
          ['restaurant_menu', 'On the menu', `${itemCount} items`],
        ].map(([icon, label, value]) => (
          <div key={label} className="flex flex-col items-center gap-space-xs px-space-sm py-space-md">
            <Icon name={icon} className="text-[20px] text-primary" />
            <span className="text-label-sm uppercase tracking-wide text-on-surface-variant">
              {label}
            </span>
            <span className="text-center text-label-md text-on-surface">{value}</span>
          </div>
        ))}
      </div>

      <div className="grid gap-space-lg lg:grid-cols-[1fr_340px]">
        <div className="flex flex-col gap-space-lg">
          {sections.length > 1 && (
            <div className="flex flex-wrap gap-space-sm">
              {sections.map((section) => (
                <a
                  key={section.id}
                  href={`#cat-${section.id}`}
                  onClick={() => setActiveCategory(section.id)}
                  className={`pill ${activeCategory === section.id ? 'pill-active' : ''}`}
                >
                  {section.name}
                </a>
              ))}
            </div>
          )}

          {sections.length === 0 ? (
            <EmptyState
              icon="restaurant_menu"
              title="No dishes yet"
              message="This stall hasn't added anything to its menu. Check back soon."
            />
          ) : (
            sections.map((section) => (
              <section key={section.id} id={`cat-${section.id}`} className="scroll-mt-28">
                <h2 className="mb-space-md text-headline-md text-on-surface">{section.name}</h2>
                <div className="flex flex-col gap-space-md">
                  {section.items.map((item) => (
                    <MenuItemRow
                      key={item.id}
                      item={item}
                      vendor={vendor}
                      disabled={!vendor.is_open}
                    />
                  ))}
                </div>
              </section>
            ))
          )}
        </div>

        <div className="hidden lg:block">
          <CartRail vendor={vendor} />
        </div>
      </div>

      {/* Mobile: the rail becomes a floating bar, as in the spec's overlay tier. */}
      <MobileCartBar vendor={vendor} />
    </div>
  );
}

function MobileCartBar({ vendor }: { vendor: VendorDetail }) {
  const { count, subtotal, isEmpty } = useCart();
  const navigate = useNavigate();
  if (isEmpty) return null;

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 border-t border-outline-variant bg-surface-container-lowest p-space-md shadow-sheet lg:hidden">
      <div className="mx-auto flex max-w-content items-center justify-between gap-space-md">
        <div>
          <p className="text-label-md text-on-surface-variant">
            {count} {count === 1 ? 'item' : 'items'}
          </p>
          <p className="text-headline-sm text-on-surface">{rupees(subtotal)}</p>
        </div>
        <button
          type="button"
          className="btn-primary flex-1 sm:flex-none"
          disabled={!vendor.is_open}
          onClick={() => navigate('/checkout')}
        >
          {vendor.is_open ? 'Review order' : 'Stall closed'}
        </button>
      </div>
    </div>
  );
}
