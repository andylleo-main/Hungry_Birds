/**
 * Types for `@cashfreepayments/cashfree-js`, which ships none of its own.
 *
 * Deliberately narrow: it describes the two calls this app makes and nothing
 * else. A wider guess would be a guess, and `any` would silently accept a
 * misspelt option - which, for a payment sheet, means a customer staring at a
 * blank modal with no error anywhere.
 */
declare module '@cashfreepayments/cashfree-js' {
  export interface CashfreeCheckoutOptions {
    /** From our own backend. The SDK takes no amount, which is the point. */
    paymentSessionId: string;
    /** '_modal' keeps the customer on the page; '_self' navigates away. */
    redirectTarget?: '_modal' | '_self' | '_blank';
    returnUrl?: string;
  }

  export interface CashfreeCheckoutResult {
    error?: { message?: string };
    redirect?: boolean;
    paymentDetails?: { paymentMessage?: string };
  }

  export interface Cashfree {
    checkout(options: CashfreeCheckoutOptions): Promise<CashfreeCheckoutResult>;
  }

  /** `mode` must match the environment the session was minted in. */
  export function load(options: { mode: 'sandbox' | 'production' }): Promise<Cashfree>;
}
