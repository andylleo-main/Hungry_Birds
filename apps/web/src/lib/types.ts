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
}

export interface MenuItem {
  id: string;
  name: string;
  description: string | null;
  price: string;
  category_id: string | null;
  image_url: string | null;
  is_available: boolean;
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
  | 'refund_pending'
  | 'refunded'
  | 'refund_failed';

const PAYMENT_LABELS: Record<PaymentStatus, string> = {
  pending: 'Not paid yet',
  paid: 'Paid',
  failed: 'Payment failed',
  expired: 'Payment window closed',
  refund_pending: 'Refund on its way',
  refunded: 'Refunded',
  refund_failed: 'Refund needs attention',
};

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

/** What the browser needs to open Cashfree's sheet. Deliberately no amount. */
export interface PaymentSession {
  payment_session_id: string;
  cf_order_id: string;
  /**
   * 'sandbox' | 'production' | 'mock'. The first two are Cashfree environments
   * and pick which one the SDK loads against; 'mock' means the backend is
   * running without a gateway and the payment is confirmed by a call to our own
   * API instead. Read from the session rather than the bundle so the two cannot
   * disagree after a deploy.
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
  total_amount: string;
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
