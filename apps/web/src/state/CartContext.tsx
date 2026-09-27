import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { MenuItem, Vendor } from '../lib/types';

export interface CartLine {
  item: MenuItem;
  quantity: number;
}

interface CartValue {
  vendor: Vendor | null;
  lines: CartLine[];
  count: number;
  subtotal: number;
  isEmpty: boolean;
  add: (vendor: Vendor, item: MenuItem) => void;
  setQuantity: (itemId: string, quantity: number) => void;
  remove: (itemId: string) => void;
  clear: () => void;
  quantityOf: (itemId: string) => number;
}

const CartContext = createContext<CartValue | null>(null);
const STORAGE_KEY = 'hb_cart';

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

  const add = useCallback((nextVendor: Vendor, item: MenuItem) => {
    // An order belongs to exactly one stall, so switching stalls resets it.
    setVendor((current) => {
      if (current && current.id !== nextVendor.id) setLines([]);
      return nextVendor;
    });
    setLines((current) => {
      const existing = current.find((l) => l.item.id === item.id);
      if (existing) {
        return current.map((l) =>
          l.item.id === item.id ? { ...l, quantity: l.quantity + 1 } : l,
        );
      }
      return [...current, { item, quantity: 1 }];
    });
  }, []);

  const setQuantity = useCallback((itemId: string, quantity: number) => {
    setLines((current) => {
      if (quantity <= 0) return current.filter((l) => l.item.id !== itemId);
      return current.map((l) => (l.item.id === itemId ? { ...l, quantity } : l));
    });
  }, []);

  const remove = useCallback((itemId: string) => {
    setLines((current) => current.filter((l) => l.item.id !== itemId));
  }, []);

  const clear = useCallback(() => {
    setLines([]);
    setVendor(null);
  }, []);

  const value = useMemo<CartValue>(() => {
    const count = lines.reduce((sum, l) => sum + l.quantity, 0);
    const subtotal = lines.reduce(
      (sum, l) => sum + Number.parseFloat(l.item.price) * l.quantity,
      0,
    );
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
      quantityOf: (itemId) => lines.find((l) => l.item.id === itemId)?.quantity ?? 0,
    };
  }, [vendor, lines, add, setQuantity, remove, clear]);

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart(): CartValue {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error('useCart must be used inside CartProvider');
  return ctx;
}
