/**
 * Loading and opening Razorpay Checkout.
 *
 * Checkout is a script, not an npm package - there is no module to import, so
 * the tag is injected once and the promise is cached. The types below are
 * hand-written and deliberately narrow: they describe the options this app
 * actually passes and nothing else. A wider guess would be a guess, and `any`
 * would silently accept a misspelt option, which for a payment sheet means a
 * customer staring at a blank modal with no error anywhere.
 */

const CHECKOUT_SRC = 'https://checkout.razorpay.com/v1/checkout.js';

/** What Checkout hands back to the page when a payment succeeds. */
export interface RazorpayHandback {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
}

export interface RazorpayOptions {
  /** The publishable key. Comes from the payment session, never the bundle. */
  key: string;
  /** Integer paise. Razorpay charges what it holds against the order, not this. */
  amount: number;
  currency: string;
  name: string;
  description?: string;
  /** Razorpay's own order id, which it minted. */
  order_id: string;
  prefill?: { name?: string; email?: string; contact?: string };
  notes?: Record<string, string>;
  theme?: { color?: string };
  handler?: (response: RazorpayHandback) => void;
  modal?: { ondismiss?: () => void; confirm_close?: boolean };
}

interface RazorpayInstance {
  open(): void;
  on(event: string, handler: (payload: unknown) => void): void;
}

declare global {
  interface Window {
    Razorpay?: new (options: RazorpayOptions) => RazorpayInstance;
  }
}

let loading: Promise<void> | null = null;

/**
 * Injects the Checkout script, once.
 *
 * Cached as the promise rather than a boolean so two near-simultaneous calls
 * wait on the same load instead of racing two script tags onto the page.
 */
export function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  if (loading) return loading;

  loading = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = CHECKOUT_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      // Cleared so a later attempt can retry rather than being stuck on a
      // rejected promise for the life of the page - a customer on a flaky
      // campus connection should be able to press Pay again.
      loading = null;
      reject(new Error('Could not load the payment sheet'));
    };
    document.head.appendChild(script);
  });

  return loading;
}

/** Brand red. Razorpay's default accent is a blue-violet, and this app has none. */
export const CHECKOUT_THEME = '#E53935';

/** Opens the sheet. Resolves once it is open; the outcome arrives via callbacks. */
export async function openCheckout(options: RazorpayOptions): Promise<void> {
  await loadRazorpay();
  if (!window.Razorpay) throw new Error('Could not load the payment sheet');
  new window.Razorpay(options).open();
}
