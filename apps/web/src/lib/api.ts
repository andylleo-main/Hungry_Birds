import type { AppUser, Order, OrderStatus, Vendor, VendorDetail } from './types';

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

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
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

async function refreshAccessToken(): Promise<boolean> {
  const refresh = tokens.refresh;
  if (!refresh) return false;
  try {
    const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    tokens.setAccess(data.access_token);
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
    try {
      const decoded = await res.json();
      if (decoded?.detail) {
        message =
          typeof decoded.detail === 'string'
            ? decoded.detail
            : // FastAPI validation errors arrive as a list of objects.
              (decoded.detail[0]?.msg ?? message);
      }
    } catch {
      // Non-JSON body; keep the generic message.
    }
    throw new ApiError(res.status, message);
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

export const api = {
  // --- Auth ---
  requestOtp: (email: string) =>
    request<{ message: string; debug_code: string | null }>('POST', '/auth/otp/request', {
      body: { email },
      auth: false,
    }),

  async verifyOtp(email: string, code: string): Promise<AuthResult> {
    const result = await request<AuthResult>('POST', '/auth/otp/verify', {
      body: { email, code },
      auth: false,
    });
    tokens.save(result.access_token, result.refresh_token);
    return result;
  },

  me: () => request<AppUser>('GET', '/auth/me'),

  updateMe: (changes: { full_name?: string; phone?: string }) =>
    request<AppUser>('PATCH', '/auth/me', { body: changes }),

  logout: () => tokens.clear(),

  // --- Vendors & menu ---
  listVendors: () => request<Vendor[]>('GET', '/vendors'),
  vendorDetail: (id: string) => request<VendorDetail>('GET', `/vendors/${id}`),

  // --- Orders ---
  placeOrder: (payload: {
    vendor_id: string;
    items: { menu_item_id: string; quantity: number }[];
    note?: string;
  }) => request<Order>('POST', '/orders', { body: payload }),

  myOrders: () => request<Order[]>('GET', '/orders'),
  order: (id: string) => request<Order>('GET', `/orders/${id}`),
  cancelOrder: (id: string) => request<Order>('POST', `/orders/${id}/cancel`),

  // --- Admin ---
  adminVendors: (pendingOnly = false) =>
    request<Vendor[]>('GET', `/admin/vendors?pending_only=${pendingOnly}`),
  approveVendor: (id: string) => request<Vendor>('POST', `/admin/vendors/${id}/approve`),
  suspendVendor: (id: string) => request<Vendor>('POST', `/admin/vendors/${id}/suspend`),
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
