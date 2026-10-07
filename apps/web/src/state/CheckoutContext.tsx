import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError, api, unavailableItems } from '../lib/api';
import { validateIndianMobile } from '../lib/format';
import { isMockPayment } from '../lib/types';
import { CHECKOUT_THEME, openCheckout } from '../lib/razorpay';
import { useAuth } from './AuthContext';
import { keyOf, lineKey, useCart } from './CartContext';
import type { CartLine, LineKey } from './CartContext';
import type {
  CashbackQuote,
  Coupon,
  DeliveryLocation,
  FulfilmentType,
  MenuItem,
} from '../lib/types';

/**
 * Everything the checkout holds, for as long as somebody is in it.
 *
 * It all lived in one `Checkout` component until the page was split in two.
 * Local state would not have survived the navigation: a customer who chose
 * delivery to Hostel 5, moved to the payment page and came back would have
 * found both answers gone, and - worse - the payment page would have had
 * nothing to send.
 *
 * So this is not an abstraction for its own sake. It is the same state, hoisted
 * to the one place that outlives both pages, with the three fetches alongside it
 * so they run once rather than once per page.
 *
 * Not in `CartContext`, which is persisted to localStorage and shared with the
 * header's cart button. None of this should survive a closed tab: a stall's
 * delivery locations go stale, and a redemption offered yesterday may not be
 * available today.
 */
interface CheckoutState {
  // --- what is being ordered ---
  lines: CartLine[];
  subtotal: number;
  count: number;
  setQuantity: (key: LineKey, next: number) => void;
  stallName: string;
  vendorId: string | undefined;

  // --- how it is handed over ---
  fulfilment: FulfilmentType | null;
  setFulfilment: (next: FulfilmentType | null) => void;
  modes: { value: FulfilmentType; label: string; icon: string; blurb: string }[];
  location: string;
  setLocation: (next: string) => void;
  locations: DeliveryLocation[] | null;
  dineInOk: boolean;

  // --- who to reach ---
  name: string;
  setName: (next: string) => void;
  phone: string;
  setPhone: (next: string) => void;
  note: string;
  setNote: (next: string) => void;

  // --- paying ---
  payLater: boolean;
  setPayLater: (next: boolean) => void;
  cashAtTheDoor: boolean;
  mockPayments: boolean;
  redeem: boolean;
  /** Ticking this drops any applied coupon: the server allows only one. */
  setRedeem: (next: boolean) => void;
  quote: CashbackQuote | null;
  /** The code applied to this order, as the server priced it. */
  coupon: Coupon | null;
  couponError: string | null;
  checkingCoupon: boolean;
  /** Returns whether it stuck, so the field can clear itself on success. */
  applyCoupon: (code: string) => Promise<boolean>;
  clearCoupon: () => void;
  applied: number;
  payable: number;

  // --- what is in the way ---
  soldOut: CartLine[];
  soldOutKeys: Set<LineKey>;
  dropSoldOut: () => void;
  shortOfMinimum: number;
  minDelivery: number;
  error: string | null;
  setError: (next: string | null) => void;
  placing: boolean;

  /** Everything that must be true before the order can be sent. */
  ready: boolean;
  /** Why it is not, in words, or null when it is. */
  blockedBecause: string | null;

  placeOrder: () => Promise<void>;
}

const CheckoutCtx = createContext<CheckoutState | null>(null);

export function useCheckout(): CheckoutState {
  const ctx = useContext(CheckoutCtx);
  if (!ctx) throw new Error('useCheckout must be used inside CheckoutProvider');
  return ctx;
}

export function CheckoutProvider({ children }: { children: ReactNode }) {
  const { vendor, lines, subtotal, count, setQuantity, clear } = useCart();
  const { user, updateProfile } = useAuth();
  const navigate = useNavigate();

  const [name, setName] = useState(user?.full_name ?? '');
  const [phone, setPhone] = useState(user?.phone ?? '');
  const [note, setNote] = useState('');
  const [placing, setPlacing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The stall's menu as it is right now, against which the cart is checked.
  // Null until the stall loads; an empty check is better than a wrong one, and
  // the server refuses the order anyway.
  const [liveMenu, setLiveMenu] = useState<Map<string, MenuItem> | null>(null);
  // Line keys the server came back and refused, if it got that far. Keys rather
  // than item ids, because one size of a dish can sell out while another is
  // still on.
  const [refused, setRefused] = useState<string[]>([]);

  // Re-read here rather than taken from the cart. The cart survives a reload in
  // localStorage, so by the time somebody reaches checkout the stall may have
  // stopped delivering, or switched off the hostel they were going to pick.
  const [fulfilment, setFulfilment] = useState<FulfilmentType | null>(null);
  /**
   * Defaults to paying now, unlike the fulfilment picker which starts
   * unselected on purpose.
   *
   * The two are not the same decision. Nobody can guess which way a customer
   * wants their food handed over, but paying up front is the safe default for
   * both sides - the stall is not cooking on trust - so cash is an explicit
   * opt-in rather than a question everybody has to answer.
   */
  const [payLater, setPayLater] = useState(false);
  const [locations, setLocations] = useState<DeliveryLocation[] | null>(null);
  const [location, setLocation] = useState('');
  const [dineInOk, setDineInOk] = useState(vendor?.dine_in_enabled ?? true);
  const [deliveryOk, setDeliveryOk] = useState(vendor?.delivery_enabled ?? true);
  // Starts at 0 rather than at the server's default, because a cart saved
  // before this field existed carries no figure and guessing 100 would refuse a
  // basket the stall would actually have taken.
  const [minDelivery, setMinDelivery] = useState(
    Number(vendor?.min_delivery_order ?? 0),
  );

  /**
   * Whether to put cashback towards this order, and what the server says that
   * is worth.
   *
   * Off by default. A balance is the student's to decide about, and quietly
   * spending it on the first order they place after earning it is not a
   * decision they made.
   */
  const [redeem, setRedeem] = useState(false);
  const [quote, setQuote] = useState<CashbackQuote | null>(null);

  /**
   * The discount code applied to this order, and why one was refused.
   *
   * Mutually exclusive with `redeem` above: the server refuses the pair with a
   * 422, so the page must not let somebody build a basket it will bounce.
   * Applying one clears the other, each saying so, rather than the button
   * failing at the end.
   *
   * `coupon` is what the server said the code is worth - never a figure worked
   * out here - so what is shown and what is charged come from one place.
   */
  const [coupon, setCoupon] = useState<Coupon | null>(null);
  const [couponError, setCouponError] = useState<string | null>(null);
  const [checkingCoupon, setCheckingCoupon] = useState(false);
  // An automatic coupon is offered already applied, and dropping one has to
  // stick - otherwise the effect that found it would put it straight back.
  const [autoDropped, setAutoDropped] = useState(false);

  // Whether this deployment is charging anybody. Read from the server rather
  // than the bundle: a hardcoded answer would go stale the moment PAYMENTS_MODE
  // changed without a rebuild.
  const [mockPayments, setMockPayments] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .config()
      .then((c) => {
        if (!cancelled) setMockPayments(c.payments_mode === 'mock');
      })
      // A failed read shows no banner. Understating is the safe direction: the
      // alternative is warning about test payments on a deployment taking real
      // money.
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const vendorId = vendor?.id;

  useEffect(() => {
    if (!vendorId) return;
    let cancelled = false;
    api
      .vendorDetail(vendorId)
      .then((detail) => {
        if (cancelled) return;
        setDineInOk(detail.dine_in_enabled);
        setDeliveryOk(detail.delivery_enabled);
        setMinDelivery(Number(detail.min_delivery_order ?? 0));
        setLocations(detail.delivery_locations);

        // Nothing is pre-selected. Dine-in used to be picked as soon as this
        // resolved, which meant somebody who wanted delivery could pay for a
        // collection without ever having made a choice.

        // The same response already carries the stall's whole menu, so keep it:
        // it catches a dish that sold out while the cart sat in localStorage,
        // before the customer reaches for their card rather than after.
        setLiveMenu(
          new Map(
            [
              ...detail.categories.flatMap((c) => c.items),
              ...detail.uncategorized_items,
            ].map((item) => [item.id, item]),
          ),
        );
      })
      .catch(() => {
        // Leave whatever the cart knew. Placing the order is still checked
        // server-side, so a failed read here costs a clear error later rather
        // than a wrong order now.
        if (!cancelled) setLocations([]);
      });
    return () => {
      cancelled = true;
    };
  }, [vendorId]);

  // Re-quoted whenever the basket changes, because the ceiling is a share of the
  // cart: removing a dish lowers what can be spent, and a stale figure would
  // promise a discount the server then declines to apply.
  useEffect(() => {
    if (!vendorId || subtotal <= 0) return;
    let cancelled = false;
    api
      .cashbackQuote(vendorId, subtotal.toFixed(2))
      .then((q) => {
        if (!cancelled) setQuote(q);
      })
      // Silent. Cashback is a bonus, and a failed read should cost the student
      // the chance to spend it rather than the chance to order.
      .catch(() => {
        if (!cancelled) setQuote(null);
      })
    return () => {
      cancelled = true;
    };
  }, [vendorId, subtotal]);

  // Derived rather than stored, so removing a struck-through dish updates the
  // banner immediately instead of leaving it claiming a problem that is gone.
  const soldOut = useMemo(() => {
    function gone(line: CartLine): boolean {
      if (refused.includes(keyOf(line))) return true;
      const live = liveMenu?.get(line.item.id);
      if (live === undefined) return false;
      if (!live.is_available) return true;
      if (!line.variant) return false;
      // The size may have been switched off, or removed from the dish entirely
      // since this cart was filled.
      const size = live.variants.find((v) => v.id === line.variant!.id);
      return size === undefined || !size.is_available;
    }
    return lines.filter(gone);
  }, [lines, liveMenu, refused]);

  const soldOutKeys = useMemo(() => new Set(soldOut.map(keyOf)), [soldOut]);

  const dropSoldOut = useCallback(() => {
    for (const line of soldOut) setQuantity(keyOf(line), 0);
    setRefused([]);
    setError(null);
  }, [soldOut, setQuantity]);

  /// Cash is a delivery-only option, so switching back to dine-in must not leave
  /// a stale choice behind - the server would refuse the order and the customer
  /// would have no idea why.
  const cashAtTheDoor = payLater && fulfilment === 'delivery';

  /// How much short of the stall's minimum this basket is, or 0 if it is fine.
  ///
  /// Delivery only, and only once delivery has actually been chosen: a basket
  /// that is being eaten at the counter is never too small.
  const shortOfMinimum =
    fulfilment === 'delivery' && minDelivery > 0 && subtotal < minDelivery
      ? minDelivery - subtotal
      : 0;

  /**
   * The quote, only while it is about the cart in front of us.
   *
   * Derived rather than cleared from inside the effect: an empty cart has
   * nothing to quote against, and a stale figure must not survive into a basket
   * it was not computed for.
   */
  const liveQuote = subtotal > 0 ? quote : null;

  // What will actually come off. One of the two at most, which the setters
  // below enforce - but written as a sum anyway, so a future third promotion
  // does not silently drop one of the first two.
  const cashbackApplied = redeem && liveQuote ? Number(liveQuote.redeemable) : 0;
  const couponApplied = coupon ? Number(coupon.discount) : 0;
  const applied = cashbackApplied + couponApplied;
  const payable = subtotal - applied;

  /**
   * Apply a typed code, or report why it does not work.
   *
   * The refusal comes from the server in words written for the person who typed
   * it - "that code is for a first order" rather than an error name - so it is
   * shown as it arrived rather than being translated here into something vaguer.
   *
   * Applying one turns cashback off. The server refuses the pair with a 422, so
   * letting somebody tick both and discover it at the end would be the worst
   * version of this: the failure would land on the Pay button.
   */
  const applyCoupon = useCallback(
    async (code: string): Promise<boolean> => {
      if (!vendorId || !code.trim()) return false;
      setCheckingCoupon(true);
      setCouponError(null);
      try {
        const found = await api.checkCoupon(code, vendorId, subtotal.toFixed(2));
        setCoupon(found);
        setRedeem(false);
        return true;
      } catch (e) {
        setCoupon(null);
        setCouponError(
          e instanceof ApiError
            ? e.message
            : "Couldn't check that code. Try again in a moment.",
        );
        return false;
      } finally {
        setCheckingCoupon(false);
      }
    },
    [vendorId, subtotal],
  );

  const clearCoupon = useCallback(() => {
    setCoupon(null);
    setCouponError(null);
    // An automatic code would otherwise be re-applied by the effect that found
    // it, so dropping one has to be remembered for as long as this checkout.
    setAutoDropped(true);
  }, []);

  /**
   * Ticking cashback drops any applied code, for the same reason as above.
   *
   * Wrapped rather than exposing the raw setter, so the exclusivity cannot be
   * bypassed by a caller that does not know about it.
   */
  const chooseCashback = useCallback((on: boolean) => {
    setRedeem(on);
    if (on) {
      setCoupon(null);
      setCouponError(null);
    }
  }, []);

  /**
   * An automatic coupon applies itself, since it has no code to type.
   *
   * Only when nothing else is in play: a student who typed their own code, or
   * chose cashback, or dropped this one already, has made a choice that an
   * automatic discount must not quietly overwrite.
   */
  useEffect(() => {
    if (!vendorId || subtotal <= 0) return;
    if (coupon || redeem || autoDropped) return;
    let cancelled = false;
    api
      .availableCoupons(vendorId, subtotal.toFixed(2))
      .then((found) => {
        const auto = found.find((c) => c.automatic);
        if (!cancelled && auto) setCoupon(auto);
      })
      // Silent: a discount nobody asked for failing to appear should not cost
      // anybody the chance to order.
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [vendorId, subtotal, coupon, redeem, autoDropped]);

  const modes = useMemo(
    () =>
      [
        dineInOk
          ? ({
              value: 'dine_in',
              label: 'Dine in',
              icon: 'restaurant',
              blurb: 'Eat at or collect from the stall',
            } as const)
          : null,
        deliveryOk
          ? ({
              value: 'delivery',
              label: 'Delivery',
              icon: 'delivery_dining',
              blurb: 'Brought to you on campus',
            } as const)
          : null,
      ].filter((m): m is NonNullable<typeof m> => m !== null),
    [dineInOk, deliveryOk],
  );

  /**
   * Why the order cannot be sent yet, in words, or null when it can.
   *
   * One place rather than a condition on the button and a different condition
   * inside placeOrder, which is how the two drifted apart before: the button
   * refused an unchosen fulfilment while the handler also checked the phone, so
   * a missing phone number was only discovered after a tap.
   */
  const blockedBecause = useMemo(() => {
    if (soldOut.length > 0) return 'Remove the sold-out items to carry on.';
    if (fulfilment === null) return 'Choose whether you want to dine in or have it delivered.';
    if (fulfilment === 'delivery' && !location)
      return 'Choose where you want your order delivered.';
    if (shortOfMinimum > 0) return 'This order is below the stall’s delivery minimum.';
    if (!name.trim()) return 'Enter your name so the stall knows who to call for.';
    const phoneError = validateIndianMobile(phone);
    if (phoneError) return phoneError;
    return null;
  }, [soldOut.length, fulfilment, location, shortOfMinimum, name, phone]);

  const ready = blockedBecause === null;

  const placeOrder = useCallback(async () => {
    if (!vendor) return;
    if (blockedBecause) {
      setError(blockedBecause);
      return;
    }

    setPlacing(true);
    setError(null);
    try {
      // The backend refuses an order from a customer with no phone, so make
      // sure the profile is saved before placing it.
      if (name.trim() !== user?.full_name || phone.trim() !== user?.phone) {
        await updateProfile({ full_name: name.trim(), phone: phone.trim() });
      }

      const order = await api.placeOrder({
        vendor_id: vendor.id,
        items: lines.map((l) => ({
          menu_item_id: l.item.id,
          // Omitted rather than sent as null for a dish without sizes: the
          // server refuses a size on a dish that has none.
          ...(l.variant ? { variant_id: l.variant.id } : {}),
          quantity: l.quantity,
        })),
        note: note.trim() || undefined,
        fulfilment_type: fulfilment!,
        // Sent only for a delivery: the server rejects a dine-in that carries
        // one rather than ignoring it, so a stray value is not harmless.
        delivery_location: fulfilment === 'delivery' ? location : undefined,
        payment_method: cashAtTheDoor ? 'cod' : 'online',
        // A flag, not an amount. The server reads the balance itself and
        // applies the most its own rules allow, so a page that is out of date
        // about the figure cannot be out of date about the decision.
        redeem_cashback: redeem,
        // One or the other, never both - the server refuses the pair, and the
        // setters above are what stop the page ever building such an order.
        coupon_code: coupon?.code,
      });

      if (cashAtTheDoor) {
        // Already placed and already in the queue - there is no payment session
        // to open, so the cart is done with.
        clear();
        navigate(`/orders/${order.id}`, { replace: true });
        return;
      }

      // The order exists but no stall has seen it yet - it is invisible until
      // the payment webhook lands. So the cart is cleared only now, and the
      // tracking page is where an unfinished payment can be picked back up.
      const session = await api.paymentSession(order.id);
      clear();

      const track = () => navigate(`/orders/${order.id}`, { replace: true });

      if (isMockPayment(session)) {
        // The backend is running without a gateway. Confirm against our own API
        // instead of opening a sheet that would have nothing behind it.
        await api.confirmMockPayment(order.id);
        track();
        return;
      }

      await openCheckout({
        key: session.key_id,
        amount: session.amount,
        currency: session.currency,
        name: 'Hungry Birds',
        description: vendor.stall_name,
        order_id: session.gateway_order_id,
        prefill: { name: name.trim(), email: user?.email, contact: phone.trim() },
        notes: { order_number: order.order_number },
        // Set explicitly. Razorpay's default accent is a blue-violet, and there
        // is no purple anywhere in this app.
        theme: { color: CHECKOUT_THEME },
        handler: (handback) => {
          // Insurance against a webhook that never arrives. The server checks
          // the signature and re-reads the amount from Razorpay, so this is only
          // trusted to say that something happened - and if it fails, the
          // webhook is still the real answer, which is why the error is
          // swallowed rather than shown.
          void api
            .confirmPayment(order.id, handback)
            .catch(() => undefined)
            .finally(track);
        },
        modal: {
          // Closed without paying. The order is still there and the tracking
          // page is where it can be picked back up.
          ondismiss: track,
        },
      });

      // openCheckout resolves once the sheet is open, not once it is finished -
      // the outcome arrives through the two callbacks above, so there is
      // deliberately no navigation here.
    } catch (err) {
      const gone = unavailableItems(err);
      if (gone) {
        // The stall sold something out between loading this page and paying for
        // it. Mark the lines so they strike through, and say it in words the
        // customer can act on - this used to print the dish's UUID.
        setRefused(gone.items.map((i) => lineKey(i.menu_item_id, i.variant_id)));
        setError('Some items are no longer available. Remove them to carry on.');
      } else {
        setError(
          err instanceof ApiError
            ? err.message
            : 'Could not start the payment. Nothing was charged - please try again.',
        );
      }
      setPlacing(false);
    }
  }, [
    vendor,
    blockedBecause,
    name,
    phone,
    note,
    fulfilment,
    location,
    cashAtTheDoor,
    redeem,
    coupon,
    lines,
    user,
    updateProfile,
    clear,
    navigate,
  ]);

  const value: CheckoutState = {
    lines,
    subtotal,
    count,
    setQuantity,
    stallName: vendor?.stall_name ?? 'This stall',
    vendorId,
    fulfilment,
    setFulfilment,
    modes,
    location,
    setLocation,
    locations,
    dineInOk,
    name,
    setName,
    phone,
    setPhone,
    note,
    setNote,
    payLater,
    setPayLater,
    cashAtTheDoor,
    mockPayments,
    redeem,
    setRedeem: chooseCashback,
    quote: liveQuote,
    coupon,
    couponError,
    checkingCoupon,
    applyCoupon,
    clearCoupon,
    applied,
    payable,
    soldOut,
    soldOutKeys,
    dropSoldOut,
    shortOfMinimum,
    minDelivery,
    error,
    setError,
    placing,
    ready,
    blockedBecause,
    placeOrder,
  };

  return <CheckoutCtx.Provider value={value}>{children}</CheckoutCtx.Provider>;
}
