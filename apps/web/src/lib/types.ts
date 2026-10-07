export type UserRole = 'customer' | 'vendor' | 'admin';

export interface AppUser {
  id: string;
  email: string;
  full_name: string | null;
  phone: string | null;
  role: UserRole;
}

export interface Vendor {
  id: string;
  stall_name: string;
  description: string | null;
  cover_image_url: string | null;
  is_approved: boolean;
  is_open: boolean;
  /** How this stall will hand food over. Both default to on server-side. */
  dine_in_enabled: boolean;
  delivery_enabled: boolean;
  /**
   * The smallest delivery this stall will cook for, as a decimal string. "0.00"
   * means none, and it never applies to dine-in.
   *
   * Optional on this type, not on the wire: a cart that was filled before this
   * shipped is still sitting in somebody's localStorage without it, and the
   * server is the authority anyway.
   */
  min_delivery_order?: string;
}

/** One size of a dish: "Half" at 120, "Full" at 200. */
export interface MenuVariant {
  id: string;
  name: string;
  price: string;
  sort_order: number;
  is_available: boolean;
}

export interface MenuItem {
  id: string;
  name: string;
  description: string | null;
  /**
   * What the dish sells at when it has no sizes. Once `variants` is non-empty
   * this is ignored for pricing — the chosen size decides — so show
   * `price_from` instead.
   */
  price: string;
  /** The cheapest size anybody can actually buy, or `price` when there are none. */
  price_from: string;
  /** Empty for most dishes. Already ordered by the server. */
  variants: MenuVariant[];
  category_id: string | null;
  image_url: string | null;
  is_available: boolean;
  /**
   * Roughly how long this dish takes, in minutes.
   *
   * Null means the stall has not said, which is not the same as instant — show
   * nothing rather than a zero.
   */
  prep_minutes: number | null;
}

export interface CategoryWithItems {
  id: string;
  name: string;
  sort_order: number;
  items: MenuItem[];
}

/** One campus drop-off point. */
export interface DeliveryLocation {
  code: string;
  label: string;
  enabled: boolean;
}

export interface VendorDetail extends Vendor {
  categories: CategoryWithItems[];
  uncategorized_items: MenuItem[];
  /**
   * Only the places this stall actually delivers to. Offering one it has
   * switched off would invite a choice the server then rejects.
   */
  delivery_locations: DeliveryLocation[];
}

export type FulfilmentType = 'dine_in' | 'delivery';

/** Where the money is, which is a separate question from where the food is. */
export type PaymentStatus =
  | 'pending'
  | 'paid'
  | 'failed'
  | 'expired'
  | 'due'
  | 'waived'
  | 'refund_pending'
  | 'refunded'
  | 'refund_failed';

const PAYMENT_LABELS: Record<PaymentStatus, string> = {
  pending: 'Not paid yet',
  paid: 'Paid',
  failed: 'Payment failed',
  expired: 'Payment window closed',
  due: 'Pay the rider on delivery',
  // Ended before anybody collected. Nothing is owed in either direction, which
  // is why this is not "cancelled" or "refunded" - no money ever moved.
  waived: 'Nothing was charged',
  refund_pending: 'Refund on its way',
  refunded: 'Refunded',
  refund_failed: 'Refund needs attention',
};

/**
 * How an order is being paid for.
 *
 * Not the gateway's name: the column has held "cashfree" and now holds
 * "razorpay" for historical rows, so anything reading it asks whether it *is*
 * cod rather than whether it is some particular gateway.
 */
export type PaymentMethod = 'online' | 'cod';

/**
 * What to show for an order's money state.
 *
 * A function rather than the bare record, because the union above is closed and
 * the server's is not. A payment state added on the backend used to render as
 * empty text here - the record returns undefined and React prints nothing - so
 * the status simply vanished from the page with no clue that anything was
 * missing. The Flutter client has carried an `unknown` member for exactly this
 * since the first new OrderStatus shipped; this is the same idea.
 */
export function paymentLabel(status: PaymentStatus | string): string {
  return PAYMENT_LABELS[status as PaymentStatus] ?? 'Updated';
}

/** What the browser needs to open Razorpay Checkout. */
export interface PaymentSession {
  /** Razorpay's own order id - it mints this, we do not choose it. */
  gateway_order_id: string;
  /** Razorpay's publishable key. Meant to reach the browser. */
  key_id: string;
  /**
   * Integer paise, from the server. Checkout needs an amount, unlike the
   * Cashfree sheet this replaces - but Razorpay charges what *it* holds against
   * the order, so editing this changes the label on the sheet and nothing about
   * the money.
   */
  amount: number;
  currency: string;
  /**
   * 'razorpay' | 'mock'. 'mock' means the backend is running without a gateway
   * and the payment is confirmed by a call to our own API instead. Read from the
   * session rather than the bundle so the two cannot disagree after a deploy.
   */
  mode: string;
  order_id: string;
}

/** True when the backend is confirming payments without charging anything. */
export function isMockPayment(session: PaymentSession): boolean {
  return session.mode === 'mock';
}

export const FULFILMENT_LABEL: Record<FulfilmentType, string> = {
  dine_in: 'Dine in',
  delivery: 'Delivery',
};

/** Mirrors the backend's OrderStatus enum. */
export type OrderStatus =
  | 'awaiting_payment'
  | 'placed'
  | 'accepted'
  | 'preparing'
  | 'ready'
  | 'out_for_delivery'
  | 'completed'
  | 'rejected'
  | 'cancelled';

export interface OrderLineItem {
  id: string;
  menu_item_id: string | null;
  name_snapshot: string;
  /** "Half", "Full", or null for a dish that has no sizes. */
  variant_name_snapshot: string | null;
  price_snapshot: string;
  quantity: number;
}

export interface Order {
  id: string;
  /**
   * What the customer quotes to support, and what the stall prints on the
   * ticket: NNNNNN-RNNN. `id` is still the identifier used in URLs and API
   * calls; this one exists to be read aloud.
   */
  order_number: string;
  /** The small number the stall calls out. Null until the order is paid for. */
  token_number: number | null;
  vendor_id: string;
  customer_id: string;
  status: OrderStatus;
  payment_method: string;
  payment_status: PaymentStatus;
  /** What the kitchen said, in minutes. Prep only — no delivery buffer. */
  prep_minutes: number | null;
  /** When to expect it, absolute and including the delivery buffer. */
  ready_by: string | null;
  /** "cash" or "upi" once a rider has collected at the door; null otherwise. */
  collected_via?: string | null;
  /**
   * What the food is worth, and what the stall is owed for it.
   *
   * Not what the customer pays when cashback was spent: Hungry Birds funds the
   * discount, so this stays the full figure. Put `amount_due` next to the word
   * "pay"; put this next to "order total".
   */
  total_amount: string;
  /** Promotional credit put towards this order. "0.00" on almost all of them. */
  cashback_applied?: string;
  /** What the customer actually hands over. */
  amount_due?: string;
  note: string | null;
  created_at: string;
  updated_at: string;
  items: OrderLineItem[];
  customer_name: string | null;
  customer_phone: string | null;
  fulfilment_type: FulfilmentType;
  delivery_location: string | null;
  /** The human name of the drop-off point; the code is what the API takes. */
  delivery_location_label: string | null;
  /**
   * Who is bringing it. Both names are null until the stall assigns the order,
   * so a rider's number is never shown to a customer they are not delivering to.
   */
  rider_id: string | null;
  rider_name: string | null;
  rider_phone: string | null;
  /** The stall is delivering this one themselves. */
  self_delivery: boolean;
  /**
   * The four digits to read out when the food arrives. Delivery orders only.
   *
   * The rider's own app never receives this - their endpoints return a payload
   * without the field - which is what makes saying it aloud proof of handover.
   */
  delivery_code: string | null;
}

/**
 * Statuses that mean "this is still happening".
 *
 * `awaiting_payment` counts, because the customer needs to find it to finish
 * paying - filing it under past orders would hide the one thing they still have
 * to do.
 */
export const ACTIVE_STATUSES: OrderStatus[] = [
  'awaiting_payment',
  'placed',
  'accepted',
  'preparing',
  'ready',
  'out_for_delivery',
];

export function isActive(status: OrderStatus): boolean {
  return ACTIVE_STATUSES.includes(status);
}

export const STATUS_LABEL: Record<OrderStatus, string> = {
  awaiting_payment: 'Payment pending',
  placed: 'Order placed',
  accepted: 'Accepted',
  preparing: 'Preparing',
  ready: 'Ready',
  out_for_delivery: 'Out for delivery',
  completed: 'Completed',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
};

/** One of the two cashback wallets. The two never mix. */
export type CashbackKind = 'normal' | 'gourmet';

/**
 * A balance, and the rate it was earned at.
 *
 * Money is a decimal string on the wire, as everywhere else here: these are
 * pydantic `Decimal`s, and turning one into a JS number to render it is how a
 * figure picks up a rounding error on the way to somebody's screen. Compare
 * with `Number(...)` only where a comparison is needed; never to display.
 */
export interface CashbackWallet {
  kind: CashbackKind;
  balance: string;
  /** The percentage this wallet earns at, and may be spent at. */
  percent: number;
  /** The most one order can earn into it. */
  cap: string;
  /** The soonest unexpired credit's date, so a student is warned rather than
   * discovering expiry by losing a balance. */
  expires_next: string | null;
}

/** One movement, for the "where did this come from" list. */
export interface CashbackEntry {
  id: string;
  kind: CashbackKind;
  /** Signed: a credit is positive, a redemption negative. */
  amount: string;
  reason: 'earned' | 'redeemed' | 'returned';
  order_id: string | null;
  /** Null where the order has since been deleted; the money is still owed. */
  stall_name: string | null;
  order_number: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface CashbackSummary {
  wallets: CashbackWallet[];
  entries: CashbackEntry[];
}

/**
 * What would actually come off a given cart.
 *
 * Worked out by the server from the same function the order path uses, which is
 * the whole reason this exists rather than the page doing the percentage
 * itself: the figure a student is shown and the figure they are charged cannot
 * then disagree.
 */
export interface CashbackQuote {
  kind: CashbackKind;
  balance: string;
  redeemable: string;
  payable: string;
  percent: number;
}

/** The promotion's shape, from /config, so the bundle hardcodes no rates. */
export interface CashbackConfig {
  normal_percent: number;
  normal_cap: string;
  gourmet_percent: number;
  gourmet_cap: string;
  /** Empty when no stall is on the better rate. */
  gourmet_stall_name: string;
  expiry_days: number;
}
