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

export interface VendorDetail extends Vendor {
  categories: CategoryWithItems[];
  uncategorized_items: MenuItem[];
}

/** Mirrors the backend's OrderStatus enum. */
export type OrderStatus =
  | 'placed'
  | 'accepted'
  | 'preparing'
  | 'ready'
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
  vendor_id: string;
  customer_id: string;
  status: OrderStatus;
  payment_method: string;
  total_amount: string;
  note: string | null;
  created_at: string;
  updated_at: string;
  items: OrderLineItem[];
  customer_name: string | null;
  customer_phone: string | null;
}

export const ACTIVE_STATUSES: OrderStatus[] = ['placed', 'accepted', 'preparing', 'ready'];

export function isActive(status: OrderStatus): boolean {
  return ACTIVE_STATUSES.includes(status);
}

export const STATUS_LABEL: Record<OrderStatus, string> = {
  placed: 'Order placed',
  accepted: 'Accepted',
  preparing: 'Preparing',
  ready: 'Ready for pickup',
  completed: 'Completed',
  rejected: 'Rejected',
  cancelled: 'Cancelled',
};
