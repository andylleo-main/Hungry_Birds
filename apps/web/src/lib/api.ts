import type { RazorpayHandback } from './razorpay';
import type {
  AdminCoupon,
  AdminCouponInput,
  AppUser,
  CashbackConfig,
  CashbackQuote,
  CashbackSummary,
  Coupon,
  CouponRedemption,
  FulfilmentType,
  Order,
  OrderStatus,
  PaymentMethod,
  PaymentSession,
  Vendor,
  VendorDetail,
} from './types';

/**
 * Empty means same-origin, which is how production runs: the backend serves
 * this SPA, so `/auth/me` resolves against whatever host it was loaded from.
 * That avoids CORS entirely and means the deployed URL isn't baked into the
 * bundle at build time.
 *
 * In dev the SPA is on Vite's port and the API on another, so point at it:
 *   VITE_API_BASE_URL=http://localhost:8000/api npm run dev
 *
 * The /api namespace matters: without it the API's GET /orders/{id} shadows
 * this app's /orders/:id tracking route, and refreshing that page returns
 * JSON instead of the app.
 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api';

const ACCESS_KEY = 'hb_access_token';
const REFRESH_KEY = 'hb_refresh_token';

/** A refusal the UI is expected to handle specially, rather than just print. */
export interface UnavailableItems {
  code: 'items_unavailable';
  message: string;
  /**
   * `variant_id` is carried separately so two sizes of one dish can be told
   * apart — keying on the item alone would strike out Half when only Full sold
   * out.
   */
  items: { menu_item_id: string; variant_id: string | null; name: string | null }[];
}

export class ApiError extends Error {
  status: number;

  /**
   * The structured body, when the server sent one instead of a sentence.
   *
   * Some refusals need the page to do something rather than show a line of
   * text - striking through the dishes that sold out, for instance. Those
   * arrive as an object with a `code`, and the page writes its own wording from
   * the parts. `message` still carries something sayable as a fallback.
   */
  detail?: UnavailableItems;

  constructor(status: number, message: string, detail?: UnavailableItems) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/** Narrows an unknown error to the sold-out refusal, for the one page that cares. */
export function unavailableItems(error: unknown): UnavailableItems | null {
  return error instanceof ApiError && error.detail?.code === 'items_unavailable'
    ? error.detail
    : null;
}

export const tokens = {
  get access() {
    return localStorage.getItem(ACCESS_KEY);
  },
  get refresh() {
    return localStorage.getItem(REFRESH_KEY);
  },
  save(access: string, refresh: string) {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  setAccess(access: string) {
    localStorage.setItem(ACCESS_KEY, access);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

/**
 * Trades the refresh token for a fresh access token - and a fresh refresh
 * token, because the server rotates on every use.
 *
 * Storing the new one is not optional. The token we just sent is now retired,
 * and sending it again is treated as a replay: the server destroys the whole
 * session on the assumption it was stolen. So a client that forgets to save
 * the rotation logs itself out on its next refresh.
 */
async function refreshAccessToken(): Promise<boolean> {
  const refresh = tokens.refresh;
  if (!refresh) return false;
  try {
    const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) {
      // Expired, revoked, or replayed - there is no way back from any of
      // them, so drop the stale pair rather than retrying with it forever.
      tokens.clear();
      return false;
    }
    const data = await res.json();
    tokens.save(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

async function request<T>(
  method: string,
  path: string,
  options: { body?: unknown; auth?: boolean; retrying?: boolean } = {},
): Promise<T> {
  const { body, auth = true, retrying = false } = options;

  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (auth && tokens.access) headers.Authorization = `Bearer ${tokens.access}`;

  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  // One silent refresh-and-retry, mirroring the Flutter client.
  if (res.status === 401 && auth && !retrying && tokens.refresh) {
    if (await refreshAccessToken()) {
      return request<T>(method, path, { ...options, retrying: true });
    }
  }

  if (!res.ok) {
    let message = `Something went wrong (${res.status})`;
    let structured: UnavailableItems | undefined;
    try {
      const decoded = await res.json();
      const detail = decoded?.detail;
      if (typeof detail === 'string') {
        message = detail;
      } else if (Array.isArray(detail)) {
        // FastAPI validation errors arrive as a list of objects.
        message = detail[0]?.msg ?? message;
      } else if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
        // A refusal the page is meant to act on rather than print. Kept whole
        // so the caller gets the parts; `message` is what it falls back to.
        structured = detail as UnavailableItems;
        message = structured.message ?? message;
      }
    } catch {
      // Non-JSON body; keep the generic message.
    }
    throw new ApiError(res.status, message, structured);
  }

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export interface AuthResult {
  access_token: string;
  refresh_token: string;
  user: AppUser;
}

export interface UserSession {
  id: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  user_agent: string | null;
  current: boolean;
}

export interface Analytics {
  range_days: number;
  generated_at: string;
  totals: {
    orders: number;
    revenue: number;
    customers: number;
    vendors: number;
    pending_vendors: number;
    active_orders: number;
  };
  orders_by_day: { day: string; orders: number; revenue: number }[];
  status_breakdown: { status: OrderStatus; count: number }[];
  top_vendors: { vendor_id: string; stall_name: string; orders: number; revenue: number }[];
}

/** A dish price, or one size of a dish. The two live in different id spaces. */
export type PriceChangeTarget = 'item' | 'variant';

/**
 * A price a stall wants to charge, waiting on an admin.
 *
 * Money arrives as strings: these are pydantic `Decimal`s, and turning them
 * into JS numbers to render them is how a price picks up a rounding error on
 * the way to somebody's screen. Format them, do not compute with them.
 */
export interface PendingPriceChange {
  target: PriceChangeTarget;
  target_id: string;
  vendor_id: string;
  stall_name: string;
  item_name: string;
  variant_name: string | null;
  current_price: string;
  pending_price: string;
  pct_change: number;
  requested_at: string | null;
}

/** What approve/reject answer with. `price` is the price now in force. */
export interface PriceDecision {
  target: PriceChangeTarget;
  target_id: string;
  price: string;
}

export const api = {
  // --- Auth ---
  requestOtp: (email: string) =>
    request<{ message: string; debug_code: string | null; resend_after_seconds: number }>(
      'POST',
      '/auth/otp/request',
      { body: { email }, auth: false },
    ),

  async verifyOtp(email: string, code: string): Promise<AuthResult> {
    const result = await request<AuthResult>('POST', '/auth/otp/verify', {
      body: { email, code },
      auth: false,
    });
    tokens.save(result.access_token, result.refresh_token);
    return result;
  },

  /** Admin sign-in with a password instead of an OTP. Only ever succeeds for
   *  an account that already holds the admin role, and only when the server
   *  has ADMIN_PASSWORD_HASH set - otherwise the route 404s. */
  async adminLogin(email: string, password: string): Promise<AuthResult> {
    const result = await request<AuthResult>('POST', '/auth/admin/login', {
      body: { email, password },
      auth: false,
    });
    tokens.save(result.access_token, result.refresh_token);
    return result;
  },

  me: () => request<AppUser>('GET', '/auth/me'),

  /** Restores a session from the refresh token alone, for a returning visitor
   *  whose access token has gone. Returns null when there is nothing to
   *  restore, so the caller can simply show the login page. */
  async restoreSession(): Promise<AppUser | null> {
    if (!tokens.refresh) return null;
    const ok = await refreshAccessToken();
    if (!ok) return null;
    try {
      return await request<AppUser>('GET', '/auth/me');
    } catch {
      tokens.clear();
      return null;
    }
  },

  listSessions: () => request<UserSession[]>('GET', '/auth/sessions'),
  endSession: (id: string) => request<void>('DELETE', `/auth/sessions/${id}`),
  endAllSessions: () => request<void>('POST', '/auth/sessions/revoke-all'),

  updateMe: (changes: { full_name?: string; phone?: string }) =>
    request<AppUser>('PATCH', '/auth/me', { body: changes }),

  /** Ends the session server-side, then clears local storage.
   *  Clearing alone used to be the whole of "sign out", which left the refresh
   *  token valid for another thirty days on whatever had a copy of it. */
  async logout(): Promise<void> {
    const refresh = tokens.refresh;
    tokens.clear();
    if (!refresh) return;
    try {
      await fetch(`${API_BASE_URL}/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      });
    } catch {
      // Offline: local state is already cleared, and the session expires on
      // its own. Failing the sign-out here would be worse than this.
    }
  },

  // --- Vendors & menu ---
  listVendors: () => request<Vendor[]>('GET', '/vendors'),
  vendorDetail: (id: string) => request<VendorDetail>('GET', `/vendors/${id}`),

  // --- Orders ---
  placeOrder: (payload: {
    vendor_id: string;
    /** `variant_id` is required for a dish with sizes and refused for one without. */
    items: { menu_item_id: string; variant_id?: string; quantity: number }[];
    note?: string;
    fulfilment_type: FulfilmentType;
    /** Required for a delivery, must be absent for a dine-in. */
    delivery_location?: string;
    /**
     * Omitted means online. "cod" is refused on a dine-in order - there is
     * nobody to collect from somebody standing at the counter.
     */
    payment_method?: PaymentMethod;
    /**
     * Put the student's matching cashback towards this order.
     *
     * A flag rather than an amount, by the same rule as the gateway amount: the
     * server reads the balance and applies the most its own rules allow. A
     * client that decided how much of a discount it was owed would be a client
     * deciding what it owes.
     */
    redeem_cashback?: boolean;
    /**
     * A discount code. Refused by the server alongside `redeem_cashback`: one
     * promotion per order, and silently dropping either would be wrong for
     * somebody.
     */
    coupon_code?: string;
  }) => request<Order>('POST', '/orders', { body: payload }),

  /**
   * Opens Razorpay Checkout for an order the caller owns.
   *
   * Returns the gateway's order id, the publishable key and the amount in paise.
   * The amount is the server's figure; Razorpay charges what it holds against
   * the order it minted, so there is nothing here worth tampering with.
   */
  paymentSession: (orderId: string) =>
    request<PaymentSession>('POST', `/orders/${orderId}/payment-session`),

  /**
   * Confirms a payment from what Checkout handed back to the page.
   *
   * The webhook remains authoritative. This exists because a misconfigured
   * webhook is otherwise a silent, total failure - nothing confirmed, every
   * order stuck unpaid - and a launch is exactly when that happens. The server
   * verifies the signature and re-reads the amount from Razorpay, so the page is
   * trusted only to say that something happened, never what.
   */
  confirmPayment: (orderId: string, handback: RazorpayHandback) =>
    request<{ status: string }>('POST', `/orders/${orderId}/payment-callback`, {
      body: handback,
    }),

  /**
   * Server facts the bundle must not hardcode. Unauthenticated, and safe to
   * call before sign-in.
   */
  config: () =>
    request<{ payments_mode: string; cashback?: CashbackConfig }>('GET', '/config'),

  // --- Cashback ---
  /** Both balances and the movements behind them. */
  cashback: () => request<CashbackSummary>('GET', '/cashback'),

  /**
   * What would come off this cart at this stall.
   *
   * The subtotal is only used for the answer - it never reaches an order, which
   * is priced from the stall's own rows - so a wrong figure here only misleads
   * the page that sent it.
   */
  // --- Coupons ---
  /**
   * What a code is worth on this cart, or a 400 carrying the reason in words.
   *
   * POST rather than GET because the code goes in the body: a code in a query
   * string lands in server logs, proxy logs and browser history, and codes are
   * worth money to whoever reads them there.
   */
  checkCoupon: (code: string, vendorId: string, subtotal: string) =>
    request<Coupon>('POST', '/coupons/check', {
      body: { code, vendor_id: vendorId, subtotal },
    }),

  /** Codes this student can use, best first. Omit the stall for the offers page. */
  availableCoupons: (vendorId: string | null, subtotal: string) =>
    request<Coupon[]>(
      'GET',
      `/coupons/available?subtotal=${encodeURIComponent(subtotal)}` +
        (vendorId ? `&vendor_id=${vendorId}` : ''),
    ),

  // --- Coupons, admin ---
  adminCoupons: () => request<AdminCoupon[]>('GET', '/admin/coupons'),
  createCoupon: (body: AdminCouponInput) =>
    request<AdminCoupon>('POST', '/admin/coupons', { body }),
  updateCoupon: (id: string, body: AdminCouponInput) =>
    request<AdminCoupon>('PUT', `/admin/coupons/${id}`, { body }),
  deleteCoupon: (id: string) => request<void>('DELETE', `/admin/coupons/${id}`),
  couponRedemptions: () =>
    request<CouponRedemption[]>('GET', '/admin/coupons/redemptions'),
  handBackRedemption: (id: string) =>
    request<CouponRedemption>(
      'POST',
      `/admin/coupons/redemptions/${id}/hand-back`,
    ),
  cleanUpExpiredCoupons: () =>
    request<{ deleted: number }>('POST', '/admin/coupons/cleanup-expired'),

  cashbackQuote: (vendorId: string, subtotal: string) =>
    request<CashbackQuote>(
      'GET',
      `/cashback/quote?vendor_id=${vendorId}&subtotal=${encodeURIComponent(subtotal)}`,
    ),

  /**
   * Stands in for paying, when the server reports mode "mock".
   *
   * Only reachable while the backend runs with PAYMENTS_MODE=mock; it 404s
   * otherwise, so there is no need to guard the call site beyond checking the
   * mode the session came back with. Nothing is charged and the order is marked
   * paid, which is the entire point: it exists to exercise everything
   * downstream of a payment before the gateway credentials do.
   */
  confirmMockPayment: (orderId: string) =>
    request<{ status: string }>('POST', `/orders/${orderId}/mock-payment`),

  myOrders: () => request<Order[]>('GET', '/orders'),
  order: (id: string) => request<Order>('GET', `/orders/${id}`),

  // --- Admin ---
  analytics: (days = 30) => request<Analytics>('GET', `/admin/analytics?days=${days}`),

  adminVendors: (pendingOnly = false) =>
    request<Vendor[]>('GET', `/admin/vendors?pending_only=${pendingOnly}`),
  approveVendor: (id: string) => request<Vendor>('POST', `/admin/vendors/${id}/approve`),
  suspendVendor: (id: string) => request<Vendor>('POST', `/admin/vendors/${id}/suspend`),

  adminPriceChanges: () =>
    request<PendingPriceChange[]>('GET', '/admin/menu/price-changes'),
  approvePriceChange: (target: PriceChangeTarget, id: string) =>
    request<PriceDecision>('POST', `/admin/menu/price-changes/${target}/${id}/approve`),
  rejectPriceChange: (target: PriceChangeTarget, id: string) =>
    request<PriceDecision>('POST', `/admin/menu/price-changes/${target}/${id}/reject`),
};

/**
 * WebSocket URL for live updates on a single order.
 *
 * A browser can't set headers on a WebSocket handshake, so whatever authorises
 * the socket has to sit in the URL - and URLs leak, into server logs, proxy
 * logs and browser history. So the access token is never put there. It buys a
 * ticket over a normal authenticated request first: single-use, dead in 30
 * seconds, and worthless to anyone who finds it in a log afterwards.
 *
 * Resolved against the page's own origin when API_BASE_URL is relative
 * (same-origin production), so this works without knowing the deployed host.
 */
export async function orderSocketUrl(orderId: string): Promise<string> {
  const { ticket } = await request<{ ticket: string; expires_in: number }>(
    'POST',
    '/realtime/ticket',
  );
  const url = new URL(`${API_BASE_URL}/ws/orders/${orderId}`, window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('ticket', ticket);
  return url.toString();
}

export type { OrderStatus };
