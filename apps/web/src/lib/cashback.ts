import { useEffect, useState } from 'react';
import { api } from './api';
import type { CashbackConfig, Vendor } from './types';

/**
 * The promotion's shape, fetched once per page load and shared.
 *
 * A module-level promise rather than a context, because every consumer wants
 * the same immutable answer and `/config` is unauthenticated: a provider would
 * be ceremony around a single cached GET. Several cards mounting at once share
 * the one request.
 *
 * Reset on nothing. The rates can change on Railway, but a student who has the
 * page open is mid-order against the figures they were shown, and a badge that
 * changed under them mid-checkout would be worse than one that is a few minutes
 * stale. A reload picks it up.
 */
let pending: Promise<CashbackConfig | null> | null = null;

function load(): Promise<CashbackConfig | null> {
  pending ??= api
    .config()
    .then((c) => c.cashback ?? null)
    // A failed read means no badges, not a broken page. The rates are
    // advertising; the server is the authority on what is actually paid.
    .catch(() => null);
  return pending;
}

export function useCashbackConfig(): CashbackConfig | null {
  const [config, setConfig] = useState<CashbackConfig | null>(null);

  useEffect(() => {
    let cancelled = false;
    void load().then((c) => {
      if (!cancelled) setConfig(c);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return config;
}

/**
 * Whether this stall is the one on the better rate.
 *
 * Matched on the name, which is how the server decides too - see
 * `kind_for` in the cashback service. Compared the same way: trimmed and
 * case-insensitive, because the name is typed once into a Railway variable and
 * once into a signup form, by two different people.
 *
 * An unset setting means no stall is Gourmet, so nothing is badged as such.
 */
export function isGourmet(vendor: Vendor, config: CashbackConfig | null): boolean {
  const wanted = config?.gourmet_stall_name.trim().toLowerCase();
  return !!wanted && vendor.stall_name.trim().toLowerCase() === wanted;
}

/** The percentage this stall pays back, or null when cashback is switched off. */
export function rateFor(vendor: Vendor, config: CashbackConfig | null): number | null {
  if (!config) return null;
  const percent = isGourmet(vendor, config)
    ? config.gourmet_percent
    : config.normal_percent;
  return percent > 0 ? percent : null;
}
