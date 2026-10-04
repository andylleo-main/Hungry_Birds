import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { MenuItem, MenuVariant, Vendor } from '../lib/types';

export interface CartLine {
  item: MenuItem;
  /** The size chosen, or null for a dish that has none. */
  variant: MenuVariant | null;
  quantity: number;
}

/**
 * What identifies a line in the cart.
 *
 * Not the item id. Once a dish can come in sizes, "Butter Paneer Half x1" and
 * "Butter Paneer Full x2" are two lines sharing one item id — they collide as
 * React keys, and every lookup finds whichever comes first. So identity is the
 * pair, and every function below takes this rather than an item id.
 *
 * Branded deliberately. A plain `string` key would make every existing
 * `setQuantity(item.id, n)` call site keep compiling while silently addressing
 * the wrong thing, and this app has no test runner — the compiler is the only
 * gate there is. The brand turns a missed call site into a build error.
 */
declare const lineKeyBrand: unique symbol;
export type LineKey = string & { readonly [lineKeyBrand]: true };

export function lineKey(itemId: string, variantId: string | null | undefined): LineKey {
  return `${itemId}:${variantId ?? ''}` as LineKey;
}

export function keyOf(line: CartLine): LineKey {
  return lineKey(line.item.id, line.variant?.id);
}

/** What one unit of a line costs: the size's price, or the dish's own. */
export function unitPrice(line: CartLine): number {
  return Number.parseFloat(line.variant?.price ?? line.item.price);
}

interface CartValue {
  vendor: Vendor | null;
  lines: CartLine[];
  count: number;
  subtotal: number;
  isEmpty: boolean;
  add: (vendor: Vendor, item: MenuItem, variant?: MenuVariant | null) => void;
  setQuantity: (key: LineKey, quantity: number) => void;
  remove: (key: LineKey) => void;
  clear: () => void;
  quantityOf: (key: LineKey) => number;
}

const CartContext = createContext<CartValue | null>(null);

/**
 * Bumped from `hb_cart` when lines gained a size.
 *
 * `load()` casts whatever it parses without validating it, so a cart written by
 * the previous build would deserialise into a line with `variant: undefined` and
 * nothing would notice — it would price at the dish's own number, which is the
 * wrong one for a dish that now has sizes. Dropping the stale cart costs one
 * person one re-add; trusting it costs a wrong price.
 */
const STORAGE_KEY = 'hb_cart_v2';

interface Persisted {
  vendor: Vendor;
  lines: CartLine[];
}

function load(): Persisted | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Persisted) : null;
  } catch {
    return null;
  }
}

export function CartProvider({ children }: { children: ReactNode }) {
  const restored = useState(() => load())[0];
  const [vendor, setVendor] = useState<Vendor | null>(restored?.vendor ?? null);
  const [lines, setLines] = useState<CartLine[]>(restored?.lines ?? []);

  // Survive a refresh mid-order; drop the key entirely once the cart empties.
  useEffect(() => {
    try {
      if (vendor && lines.length > 0) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ vendor, lines }));
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // Private mode or blocked storage - the cart just won't persist.
    }
  }, [vendor, lines]);

  const add = useCallback(
    (nextVendor: Vendor, item: MenuItem, variant: MenuVariant | null = null) => {
      // An order belongs to exactly one stall, so switching stalls resets it.
      setVendor((current) => {
        if (current && current.id !== nextVendor.id) setLines([]);
        return nextVendor;
      });
      const key = lineKey(item.id, variant?.id);
      setLines((current) => {
        const existing = current.find((l) => keyOf(l) === key);
        if (existing) {
          return current.map((l) => (keyOf(l) === key ? { ...l, quantity: l.quantity + 1 } : l));
        }
        return [...current, { item, variant, quantity: 1 }];
      });
    },
    [],
  );

  const setQuantity = useCallback((key: LineKey, quantity: number) => {
    setLines((current) => {
      if (quantity <= 0) return current.filter((l) => keyOf(l) !== key);
      return current.map((l) => (keyOf(l) === key ? { ...l, quantity } : l));
    });
  }, []);

  const remove = useCallback((key: LineKey) => {
    setLines((current) => current.filter((l) => keyOf(l) !== key));
  }, []);

  const clear = useCallback(() => {
    setLines([]);
    setVendor(null);
  }, []);

  const value = useMemo<CartValue>(() => {
    const count = lines.reduce((sum, l) => sum + l.quantity, 0);
    // unitPrice, not l.item.price. The dish's own price is ignored once a size
    // is chosen, so reading it here would quote a total the server will not
    // charge - and the customer would see the discrepancy only on the receipt.
    const subtotal = lines.reduce((sum, l) => sum + unitPrice(l) * l.quantity, 0);
    return {
      vendor: lines.length > 0 ? vendor : null,
      lines,
      count,
      subtotal,
      isEmpty: lines.length === 0,
      add,
      setQuantity,
      remove,
      clear,
      quantityOf: (key) => lines.find((l) => keyOf(l) === key)?.quantity ?? 0,
    };
  }, [vendor, lines, add, setQuantity, remove, clear]);

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart(): CartValue {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error('useCart must be used inside CartProvider');
  return ctx;
}
