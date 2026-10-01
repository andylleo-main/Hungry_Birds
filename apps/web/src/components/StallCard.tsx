import { Link } from 'react-router-dom';
import type { Vendor } from '../lib/types';
import { placeholderGradient } from '../lib/format';
import { Icon } from './ui';

export default function StallCard({ vendor }: { vendor: Vendor }) {
  return (
    <Link
      to={`/stall/${vendor.id}`}
      className="card group flex flex-col overflow-hidden transition-all hover:-translate-y-0.5 hover:shadow-card-hover"
    >
      <div className="relative aspect-[16/10] overflow-hidden">
        {vendor.cover_image_url ? (
          <img
            src={vendor.cover_image_url}
            alt={vendor.stall_name}
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          />
        ) : (
          <div
            className={`flex h-full w-full items-center justify-center bg-gradient-to-br ${placeholderGradient(vendor.id)}`}
          >
            <Icon name="storefront" className="text-[40px] text-primary/50" />
          </div>
        )}

        {/* Scrim so the status pill stays readable over any photo. */}
        <div className="absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-black/45 to-transparent" />

        <span
          className={`absolute bottom-space-sm left-space-sm inline-flex h-6 items-center gap-space-xs rounded-full px-space-sm text-label-sm uppercase tracking-[0.02em] ${
            vendor.is_open ? 'bg-success text-white' : 'bg-on-surface/80 text-white'
          }`}
        >
          <Icon name={vendor.is_open ? 'schedule' : 'bedtime'} className="text-[14px]" />
          {vendor.is_open ? 'Open now' : 'Closed'}
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-space-xs p-space-md">
        <h3 className="truncate text-headline-sm text-on-surface">{vendor.stall_name}</h3>
        <p className="line-clamp-2 min-h-[40px] text-body-sm text-on-surface-variant">
          {vendor.description ?? 'Freshly made on campus.'}
        </p>
        <div className="mt-space-xs flex items-center gap-space-md border-t border-outline-variant pt-space-sm text-label-md text-on-surface-variant">
          <span className="flex items-center gap-space-xs">
            <Icon name="storefront" className="text-[16px] text-primary" />
            Pickup
          </span>
          <span className="flex items-center gap-space-xs">
            <Icon name="credit_card" className="text-[16px] text-primary" />
            Pay online
          </span>
        </div>
      </div>
    </Link>
  );
}
