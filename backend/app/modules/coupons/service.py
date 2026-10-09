"""Whether a code applies, what it is worth, and what happens to the use.

Two halves. The first is a pure question - given a coupon, a cart and a student,
may this be used and for how much - which is asked twice: once when checkout
previews it and once when the order is actually placed. It is one function for
the reason the cashback quote is one function: a student shown one figure and
charged against another stops trusting the app and never reports it as a bug.

The second half is the use itself, which has three states and two ways out. It is
**held** at placement, **consumed** on completion, and **returned** when a stall
refuses the order or an admin hands it back. Deliberately the same shape as
cashback's hold/credit/return, so there is one story about what a refused order
undoes rather than two.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.coupon import (
    Coupon,
    CouponAudience,
    CouponAudienceMember,
    CouponRedemption,
    CouponVendor,
    DiscountType,
    ExpiryType,
    RedemptionState,
)
from app.db.models.order import Order, OrderStatus
from app.db.models.user import User

log = logging.getLogger(__name__)

# What a coupon may never take an order below.
#
# An admin can write "100% off" or a flat ₹500 on a ₹200 cart, and nothing about
# either is a mistake worth refusing outright - but an order with nothing left to
# pay would need a ₹0 Razorpay order, which the gateway will not open, and a
# whole second path for marking it paid without one. So the discount is trimmed
# to leave this much, and the customer is told the figure that was actually
# applied rather than the one on the poster.
MINIMUM_PAYABLE = Decimal("1")


class CouponError(Exception):
    """A coupon that cannot be used, with the reason in words a student can act on.

    An exception rather than a returned error, because both callers want to stop:
    checkout to show it, place_order to refuse. The message is written for the
    person typing the code - "this code is for your first order" rather than
    "audience mismatch" - since it goes straight onto their screen.
    """

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def as_http(self) -> HTTPException:
        return HTTPException(status.HTTP_400_BAD_REQUEST, self.message)


def normalise(code: str) -> str:
    """How a code is stored and compared.

    Upper-cased and stripped, because this is read off a poster and typed by a
    hungry person on a phone keyboard that likes to lower-case the first letter.
    """
    return code.strip().upper()


def _floor_rupees(amount: Decimal) -> Decimal:
    """Down to whole rupees, as every figure in this app is.

    Down rather than nearest, for the same reason cashback rounds down: a cap
    that rounds up pays out more than the admin typed.
    """
    return amount.quantize(Decimal("1"), rounding=ROUND_DOWN)


def worth_on(coupon: Coupon, subtotal: Decimal) -> Decimal:
    """What this coupon takes off a cart of this size.

    Three ceilings, smallest wins: the coupon's own value, its max_discount if it
    is a percentage, and whatever leaves MINIMUM_PAYABLE behind.

    max_discount is ignored on a flat coupon on purpose. "20% off, up to ₹50" is
    a sentence; "₹100 off, up to ₹50" is a contradiction, and silently honouring
    the smaller number would mean an admin's ₹100 code quietly paying ₹50.
    """
    if subtotal <= 0:
        return Decimal("0")

    if coupon.discount_type is DiscountType.PERCENT:
        raw = Decimal(subtotal) * Decimal(coupon.discount_value) / Decimal(100)
        if coupon.max_discount is not None:
            raw = min(raw, Decimal(coupon.max_discount))
    else:
        raw = Decimal(coupon.discount_value)

    headroom = Decimal(subtotal) - MINIMUM_PAYABLE
    return max(_floor_rupees(min(raw, headroom)), Decimal("0"))


async def live_uses(coupon_id: uuid.UUID, db: AsyncSession) -> int:
    """How many uses this coupon has actually spent.

    Derived, never stored. A stored counter drifts from the rows behind it the
    first time anything goes wrong, and then needs a repair button that exists
    only because the counter does. Held uses count: a use reserved by an order
    somebody is still paying for is not available to anybody else.
    """
    return (
        await db.scalar(
            select(func.count())
            .select_from(CouponRedemption)
            .where(
                CouponRedemption.coupon_id == coupon_id,
                CouponRedemption.state != RedemptionState.RETURNED,
            )
        )
    ) or 0


async def stalls_for(coupon_id: uuid.UUID, db: AsyncSession) -> set[uuid.UUID]:
    """The stalls this code is pinned to.

    Only meaningful when the coupon's `all_stalls` is off; a code good everywhere
    has no rows here and nobody should be asking. An empty set on a pinned coupon
    means it works **nowhere** - every stall it named has since been deleted -
    which is the safe way round, and `Coupon.all_stalls` says why at length.

    Read here rather than through the relationship, which is `lazy="raise"` like
    every other collection on Coupon: the coupon is usually loaded by a locking
    SELECT with nothing eager-loaded, and a lazy load inside an async session is
    the kind of thing that works in a test and deadlocks under load.
    """
    rows = await db.execute(
        select(CouponVendor.vendor_id).where(CouponVendor.coupon_id == coupon_id)
    )
    return set(rows.scalars().all())


async def _used_by(coupon_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(CouponRedemption)
            .where(
                CouponRedemption.coupon_id == coupon_id,
                CouponRedemption.user_id == user_id,
                CouponRedemption.state != RedemptionState.RETURNED,
            )
        )
    ) or 0


async def _has_completed_an_order(user_id: uuid.UUID, db: AsyncSession) -> bool:
    """Whether this student has ever actually received food from here.

    Completed, not placed. A first-order code should survive an order that was
    rejected or abandoned at the payment screen - those customers have still
    never been served, which is who the code is for.
    """
    found = await db.execute(
        select(Order.id)
        .where(Order.customer_id == user_id, Order.status == OrderStatus.COMPLETED)
        .limit(1)
    )
    return found.first() is not None


async def find(code: str, db: AsyncSession, *, lock: bool = False) -> Coupon:
    """The coupon for this code, or a refusal that does not confirm it exists.

    `lock` takes `SELECT … FOR UPDATE` on the row, which is what makes the use
    limits true under concurrency: every check and insert for one code is then
    serialised, so two checkouts cannot both see "1 use left" and both take it.
    Only the placement path locks; a preview has nothing to protect.
    """
    query = select(Coupon).where(Coupon.code == normalise(code))
    if lock:
        query = query.with_for_update()
    coupon = (await db.execute(query)).scalar_one_or_none()
    if coupon is None:
        raise CouponError("That code isn't one we know. Check it and try again.")
    return coupon


@dataclass(frozen=True)
class Applied:
    """A coupon that may be used on this cart, and what it is worth there."""

    coupon: Coupon
    discount: Decimal


async def assert_usable(
    coupon: Coupon,
    user: User,
    vendor_id: uuid.UUID | None,
    subtotal: Decimal,
    db: AsyncSession,
) -> Applied:
    """Every reason a code might not apply, checked in the order a person would.

    Raises CouponError with the reason. The order matters: the general facts
    about the coupon come before the ones about this student, so somebody told
    "that code has run out" is not first told it is not for them.

    Called by both the preview endpoint and place_order, which is the point - the
    figure shown and the figure charged come from one place and cannot disagree.

    `vendor_id` None means the caller is not asking about a particular stall -
    the offers page, which has no cart yet - and the stall check is skipped. Only
    site-wide coupons are ever asked about that way; `available_for` filters the
    pinned ones out before getting here, because a stall-pinned code cannot be
    judged without knowing which stall.
    """
    now = datetime.now(timezone.utc)

    if not coupon.is_active:
        raise CouponError("That code isn't active any more.")

    if coupon.expiry_type is ExpiryType.DATE:
        if coupon.expires_at is not None and coupon.expires_at <= now:
            raise CouponError("That code has expired.")
    elif coupon.max_uses is not None and await live_uses(coupon.id, db) >= coupon.max_uses:
        raise CouponError("That code has been fully claimed.")

    # Read here rather than at the top of this function, which is where it used
    # to be. The lookup is only ever needed by this one branch, and hoisting it
    # meant every coupon paid for it - including the site-wide ones, which are
    # most of them, and the ones already refused as inactive or expired a few
    # lines above. `available_for` runs this whole function once per candidate on
    # every cart change, so a query that is usually unnecessary is worth not
    # issuing.
    if vendor_id is not None and not coupon.all_stalls:
        if vendor_id not in await stalls_for(coupon.id, db):
            # Deliberately does not name the stalls it *is* for. A pinned code is
            # usually a deal those stalls are running, and turning a wrong guess
            # into an advertisement for somebody else is not ours to do.
            #
            # An empty set lands here too, which is deliberate: every stall the
            # code named has been deleted, so it works nowhere. See
            # Coupon.all_stalls.
            raise CouponError("That code doesn't work at this stall.")

    if Decimal(subtotal) < Decimal(coupon.min_order_value):
        short = Decimal(coupon.min_order_value) - Decimal(subtotal)
        raise CouponError(
            f"That code needs an order of ₹{coupon.min_order_value:.0f} or more. "
            f"Add ₹{short:.0f} more to use it."
        )

    if coupon.audience is CouponAudience.FIRST_ORDER:
        if await _has_completed_an_order(user.id, db):
            raise CouponError("That code is for a first order.")
    elif coupon.audience is CouponAudience.NAMED:
        allowed = await db.execute(
            select(CouponAudienceMember.email).where(
                CouponAudienceMember.coupon_id == coupon.id,
                CouponAudienceMember.email == user.email.strip().lower(),
            )
        )
        if allowed.first() is None:
            raise CouponError("That code is for a different account.")

    if coupon.one_per_customer and await _used_by(coupon.id, user.id, db) > 0:
        raise CouponError("You've already used that code.")

    discount = worth_on(coupon, Decimal(subtotal))
    if discount <= 0:
        # Reachable on a cart so small that the floor eats the whole discount -
        # a ₹1 cart with any coupon at all. Saying "worth nothing here" is more
        # use than applying a code that changes no figure on the screen.
        raise CouponError("That code isn't worth anything on an order this small.")

    return Applied(coupon=coupon, discount=discount)


# --- the use itself ---------------------------------------------------------
#
# Hold, consume, hand back. The same three moments cashback has, at the same
# three call sites, for the same reasons.


async def hold_onto(
    order: Order,
    user: User,
    code: str,
    subtotal: Decimal,
    db: AsyncSession,
) -> Decimal:
    """Reserve one use of a code against an order being placed.

    Called from place_order, inside its transaction, after the basket has been
    priced from the stall's own rows. Sets `order.coupon_discount` and writes the
    held row; the caller commits both together, so an order can never exist
    carrying a discount no use was taken for.

    **The coupon row is locked first.** Everything the limits depend on - how
    many uses are spent, whether this student has had one - is a read followed
    by a write, and two checkouts in the same instant would otherwise both read
    "one left" and both take it. The lock is held to commit, which serialises
    every use of one code and makes the per-customer rule true as well.

    Raises CouponError, which the caller turns into a 400. A bad code must fail
    the order rather than quietly placing it at full price: somebody who typed a
    code expects it to count, and an order that silently ignored it is a refund
    conversation.

    Cashback already on the order is a different matter - see the guard below.
    """
    # The mirror of the guard in `cashback.redeem_onto`, for the same reason and
    # with the same reasoning about raising: one promotion per order, refused at
    # the boundary by `OrderCreate.one_promotion_at_a_time`, so a caller that
    # gets here has broken a rule rather than typed something wrong.
    #
    # Not a CouponError, deliberately: that is the type whose messages are
    # written to be read by the person who typed the code, and "an order cannot
    # carry two promotions" is not their mistake to fix.
    if Decimal(order.cashback_applied) > 0:
        raise ValueError(
            "cannot hold a coupon against an order that already has cashback applied"
        )

    coupon = await find(code, db, lock=True)
    applied = await assert_usable(coupon, user, order.vendor_id, subtotal, db)

    # The coupon no longer comes off the price: its value is credited as
    # cashback when the order completes (cashback.credit_for_completed_order),
    # so order.coupon_discount stays zero and the student pays in full.
    db.add(
        CouponRedemption(
            coupon_id=coupon.id,
            user_id=user.id,
            order_id=order.id,
            discount=applied.discount,
            state=RedemptionState.HELD,
            created_at=datetime.now(timezone.utc),
        )
    )
    return applied.discount


async def _redemption_for(order_id: uuid.UUID, db: AsyncSession) -> CouponRedemption | None:
    return (
        await db.execute(
            select(CouponRedemption).where(CouponRedemption.order_id == order_id)
        )
    ).scalars().first()


async def consume_for_completed_order(order: Order, db: AsyncSession) -> bool:
    """The order finished, so the use sticks.

    Called from both routes that reach COMPLETED - the stall's and the rider's -
    so it has to be idempotent, and it is by construction: a row already
    consumed is left alone rather than written again.

    Nothing is counted here that was not already counted at placement. A held use
    is as unavailable to everybody else as a consumed one; this only records that
    it will not be coming back.
    """
    row = await _redemption_for(order.id, db)
    if row is None or row.state is not RedemptionState.HELD:
        return False
    row.state = RedemptionState.CONSUMED
    row.settled_at = datetime.now(timezone.utc)
    return True


async def hand_back(order_id: uuid.UUID, db: AsyncSession) -> Decimal:
    """Give the use back.

    Two callers, one function. The stall refusing an order calls it automatically
    from the REFUNDABLE_ENDINGS block, and an admin calls it by hand from the
    redemptions log - which is the same action, so it is the same code rather
    than a second path that can disagree with the first.

    Returns what was given back, or zero when there was nothing to give. Safe to
    call twice: a row already returned is left alone, so the admin's button and
    the automatic path cannot both credit the same use.

    The order's own `coupon_discount` is **not** cleared. It is what the customer
    was actually charged against, and a refund is computed from it; zeroing it
    here would make a refused order look as though it had never had a discount.
    """
    row = await _redemption_for(order_id, db)
    if row is None or row.state is RedemptionState.RETURNED:
        return Decimal("0")

    row.state = RedemptionState.RETURNED
    row.settled_at = datetime.now(timezone.utc)
    return Decimal(row.discount)


async def available_for(
    user: User,
    vendor_id: uuid.UUID | None,
    subtotal: Decimal,
    db: AsyncSession,
) -> list[Applied]:
    """Codes this student could use right now, for the offers page and checkout.

    Only coupons an admin ticked *show in offers*, plus every `automatic` one -
    those have no code to type, so not listing them would make them invisible
    until they applied themselves.

    Eligibility is decided by running the same `assert_usable` the order path
    runs and keeping the ones that do not raise. Slower than a clever query and
    correct by construction: there is one definition of "usable", so a coupon can
    never be advertised here and then refused at checkout.

    `vendor_id` None means "anywhere" - the offers page asks without a stall in
    mind, and gets only the site-wide codes, since a stall-pinned one cannot be
    judged without knowing the cart it is for.
    """
    rows = (
        await db.execute(
            select(Coupon).where(
                Coupon.is_active.is_(True),
                Coupon.show_in_offers.is_(True)
                | (Coupon.audience == CouponAudience.AUTOMATIC),
            )
        )
    ).scalars().all()

    out: list[Applied] = []
    for coupon in rows:
        if vendor_id is None and not coupon.all_stalls:
            continue
        try:
            out.append(await assert_usable(coupon, user, vendor_id, subtotal, db))
        except CouponError:
            continue
    # Best first, so a checkout offering one automatic coupon offers the right
    # one and the offers page leads with what is worth most.
    out.sort(key=lambda a: a.discount, reverse=True)
    return out
