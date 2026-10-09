import { Link } from 'react-router-dom';
import type { Vendor } from '../lib/types';
import { placeholderGradient } from '../lib/format';
import { isGourmet, rateFor, useCashbackConfig } from '../lib/cashback';
import { Icon } from './ui';

export default function StallCard({ vendor, index = 0 }: { vendor: Vendor; index?: number }) {
  const cashback = useCashbackConfig();
  const percent = rateFor(vendor, cashback);
  const gourmet = isGourmet(vendor, cashback);

  return (
    <Link
      to={`/stall/${vendor.id}`}
      data-testid={`stall-card-${vendor.id}`}
      style={{ animationDelay: `${Math.min(index, 8) * 60}ms` }}
      className={`card group flex animate-rise flex-col overflow-hidden transition-[transform,box-shadow,border-color] duration-300 hover:-translate-y-1 hover:border-primary/40 hover:shadow-card-hover ${
        vendor.is_open ? '' : 'opacity-80'
      }`}
    >
      <div className="relative aspect-[16/10] overflow-hidden">
        {vendor.cover_image_url ? (
          <img
            src={vendor.cover_image_url}
            alt={vendor.stall_name}
            loading="lazy"
            className={`h-full w-full object-cover transition-transform duration-500 group-hover:scale-105 ${
              vendor.is_open ? '' : 'grayscale'
            }`}
          />
        ) : (
          <div
            className={`flex h-full w-full items-end bg-gradient-to-br p-space-md ${placeholderGradient(vendor.id)}`}
          >
            <span className="font-display text-[56px] font-extrabold leading-none text-primary/20">
              {vendor.stall_name.charAt(0)}
            </span>
          </div>
        )}

        <span
          className={`absolute left-space-sm top-space-sm inline-flex h-7 items-center gap-[6px] rounded-full px-space-sm text-label-sm uppercase ${
            vendor.is_open ? 'bg-white text-success' : 'bg-on-surface text-white'
          }`}
        >
          <span className={`h-2 w-2 rounded-full ${vendor.is_open ? 'animate-pulse bg-success' : 'bg-white/60'}`} />
          {vendor.is_open ? 'Open now' : 'Closed'}
        </span>

        {percent !== null && (
          <span
            data-testid={`stall-card-cashback-${vendor.id}`}
            className={`absolute right-space-sm top-space-sm inline-flex h-7 items-center gap-space-xs rounded-full px-space-sm text-label-sm uppercase ${
              gourmet ? 'bg-on-surface text-white' : 'bg-primary text-on-primary'
            }`}
          >
            <Icon name="redeem" className="text-[14px]" />
            {percent}% back
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-space-xs p-space-md">
        <div className="flex items-start justify-between gap-space-sm">
          <h3 className="truncate text-headline-sm text-on-surface">{vendor.stall_name}</h3>
          <Icon
            name="arrow_outward"
            className="text-[20px] text-on-surface-variant transition-[color,transform] duration-300 group-hover:rotate-45 group-hover:text-primary"
          />
        </div>
        <p className="line-clamp-2 min-h-[40px] text-body-sm text-on-surface-variant">
          {vendor.description ?? 'Made fresh, right here on campus.'}
        </p>
        <div className="mt-auto flex flex-wrap items-center gap-space-xs pt-space-sm">
          {vendor.dine_in_enabled && (
            <span className="inline-flex items-center gap-[4px] rounded-full bg-surface-container px-space-sm py-[3px] text-label-sm text-on-surface-medium">
              <Icon name="restaurant" className="text-[13px]" /> Dine in
            </span>
          )}
          {vendor.delivery_enabled && (
            <span className="inline-flex items-center gap-[4px] rounded-full bg-surface-container px-space-sm py-[3px] text-label-sm text-on-surface-medium">
              <Icon name="delivery_dining" className="text-[13px]" /> Delivery
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
