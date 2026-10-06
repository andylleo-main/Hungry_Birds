"""What one stall earned, sold and turned away.

Deliberately a separate response model from the admin's, not the same one with a
filter on it. `AnalyticsOut` carries `customers`, `vendors`, `pending_vendors`
and `top_vendors` - the last being every other stall's revenue. Reducing that to
one row with a `vendor_id` filter and shipping it would be the easiest possible
way to leak a competitor's takings, and it would look correct in review. Two
models means those fields do not exist on this response at all.

The computation shares what should be shared: EARNING_STATUSES and the paid
predicate are imported rather than restated, so "what counts as revenue" has one
definition and a status added later cannot mean different things to the two
screens.

What a stall owner is actually asking, which the admin view does not answer:
what sold, when the rush is, and how much they turned away.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.menu import MenuItem
from app.db.models.order import FulfilmentType, Order, OrderStatus
from app.db.models.payment import PaymentStatus
from app.modules.admin.analytics import ACTIVE_STATUSES, EARNING_STATUSES

# The campus runs on IST. Every "day" and "hour" below is bucketed in it rather
# than UTC, which is a real bug on this screen and not a nicety: UTC midnight is
# 05:30 local, so a UTC day splits an evening rush across two bars and starts
# "today" in the middle of breakfast. A merchant reads these numbers against a
# cash box and will argue with them.
IST = "Asia/Kolkata"


def _local(column):
    """A timestamp read on the stall's own calendar."""
    return func.timezone(IST, column)


class MoneySplit(BaseModel):
    """One slice of the takings.

    `orders` counts the *paid* orders in this slice, not every order placed, so
    the four slices add up to `revenue` exactly. A stall reads this against a
    cash box and a bank statement; a split whose parts did not sum to the whole
    would be worse than no split at all.
    """

    orders: int
    revenue: float


class VendorTotals(BaseModel):
    orders: int
    revenue: float
    # Out but not handed over - what is on the counter right now.
    active_orders: int
    # Orders this stall refused or cancelled, and what they were worth. A stall
    # turning away one order in seven is about to lose its customers, and today
    # it has no way to see that.
    refused_orders: int
    refused_value: float

    # Where the money came from, two ways. Each pair sums to `revenue`.
    #
    # The stall asked for this because "taken" answers nothing they can act on:
    # dine-in and delivery are different amounts of work for the same rupee, and
    # cash is the half they have to physically count.
    dine_in: MoneySplit
    delivery: MoneySplit

    # Cash is the narrow one: a pay-on-delivery order somebody handed notes for.
    #
    # Everything else paid is "prepaid", and that deliberately includes a
    # pay-on-delivery order settled by scanning the QR. It was placed as cash
    # but it did not arrive as cash - Razorpay has it, it lands in the same
    # settlement as an order paid up front, and it is not in the till. Counting
    # it as cash would have a stall hunting for money that was never there.
    cash: MoneySplit
    prepaid: MoneySplit

    # The same money crossed both ways, so the stall can see which combination
    # it is actually running on. The four cells sum to `revenue`, and each pair
    # of them sums to the margin above - a dine-in that is not prepaid is a
    # dine-in paid in cash, and so on.
    #
    # dine_in_cash is structurally always zero: OrderCreate.cash_is_for_deliveries
    # refuses pay-on-delivery on a dine-in order, because there is nobody to
    # collect from somebody standing at the counter. It is reported anyway
    # rather than omitted, because a cell that should be empty and is not says a
    # rule has been broken somewhere, and that is worth being able to see.
    dine_in_prepaid: MoneySplit
    dine_in_cash: MoneySplit
    delivery_prepaid: MoneySplit
    delivery_cash: MoneySplit

    # Money owed right now: pay-on-delivery orders the stall is making or has
    # sent out, that nobody has collected for yet. Not revenue - nothing has
    # been paid - which is exactly why it is worth a figure of its own. It is
    # the stall's exposure, and the reason pay on delivery reversed a standing
    # rule.
    outstanding: MoneySplit

    # Money that went back out. A stall that refuses orders after they are paid
    # for sees `refused_value` as order value; this is what was actually
    # returned.
    refunded: MoneySplit


class DayPoint(BaseModel):
    day: date
    orders: int
    revenue: float


class HourPoint(BaseModel):
    """Orders by hour of the local day. A stall staffs by hour, not by day."""

    hour: int
    orders: int


class TopDish(BaseModel):
    name: str
    # Null for a dish with no sizes. Separate from the name rather than appended
    # to it, so the same dish groups across its sizes and still breaks down by
    # them - which is why OrderItem snapshots them in two columns.
    variant_name: str | None
    quantity: int
    revenue: float


class VendorAnalyticsOut(BaseModel):
    range_days: int
    generated_at: datetime
    totals: VendorTotals
    orders_by_day: list[DayPoint]
    hours: list[HourPoint]
    top_dishes: list[TopDish]
    # So "2 price changes waiting on the admin" surfaces on the dashboard rather
    # than being buried in the menu screen.
    pending_price_changes: int


async def build_vendor_analytics(
    days: int, vendor_id: uuid.UUID, db: AsyncSession
) -> VendorAnalyticsOut:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    mine = Order.vendor_id == vendor_id
    window = Order.created_at >= since
    earning = Order.status.in_(EARNING_STATUSES) & (
        Order.payment_status == PaymentStatus.PAID.value
    )
    refused = Order.status.in_([OrderStatus.REJECTED, OrderStatus.CANCELLED])

    orders_total = await db.scalar(
        select(func.count()).select_from(Order).where(mine, window)
    )
    revenue_total = await db.scalar(
        select(func.coalesce(func.sum(Order.total_amount), 0)).where(mine, window, earning)
    )
    # Not windowed, like the admin's. "What is on my counter" is a question about
    # now, not about the last thirty days.
    active_orders = await db.scalar(
        select(func.count()).select_from(Order).where(mine, Order.status.in_(ACTIVE_STATUSES))
    )
    refused_orders = await db.scalar(
        select(func.count()).select_from(Order).where(mine, window, refused)
    )
    refused_value = await db.scalar(
        select(func.coalesce(func.sum(Order.total_amount), 0)).where(mine, window, refused)
    )

    # --- where the money came from --------------------------------------------
    #
    # One query with FILTER rather than eight scalars: the four slices are two
    # partitions of the same set of rows, and computing them together is both
    # cheaper and the only way they cannot drift out of agreement with each
    # other or with `revenue`.
    #
    # coalesce on collected_via rather than a bare `== "cash"` because that
    # column is null on everything paid online, and in SQL `null = 'cash'` is
    # null, not false - which would drop those rows out of *both* slices and
    # quietly lose their revenue from the split.
    in_cash = (Order.payment_method == "cod") & (
        func.coalesce(Order.collected_via, "") == "cash"
    )
    is_dine_in = Order.fulfilment_type == FulfilmentType.DINE_IN

    def _slice(condition):
        return (
            func.count().filter(condition).label("orders"),
            func.coalesce(
                func.sum(func.coalesce(Order.total_amount, 0)).filter(condition), 0
            ).label("revenue"),
        )

    def _cell(name, condition):
        """Both numbers for one slice, labelled so the row reads back by name."""
        orders_col, revenue_col = _slice(condition)
        return [orders_col.label(f"{name}_orders"), revenue_col.label(f"{name}_revenue")]

    columns = [
        # The margins.
        *_cell("dine", is_dine_in),
        *_cell("delivery", ~is_dine_in),
        *_cell("cash", in_cash),
        *_cell("prepaid", ~in_cash),
        # And the same money crossed both ways.
        *_cell("dine_prepaid", is_dine_in & ~in_cash),
        *_cell("dine_cash", is_dine_in & in_cash),
        *_cell("delivery_prepaid", ~is_dine_in & ~in_cash),
        *_cell("delivery_cash", ~is_dine_in & in_cash),
    ]

    split = (await db.execute(select(*columns).where(mine, window, earning))).one()

    # --- money that is not revenue ---------------------------------------------
    #
    # Both of these sit outside the splits above on purpose: `earning` requires
    # a paid order, and neither of these is one. Mixing them in would break the
    # property that makes the breakdown worth showing - that its parts add up to
    # the takings.
    owed = (
        await db.execute(
            select(
                func.count().label("orders"),
                func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
            ).where(
                mine,
                window,
                Order.status.in_(EARNING_STATUSES),
                Order.payment_status == PaymentStatus.DUE.value,
            )
        )
    ).one()

    returned = (
        await db.execute(
            select(
                func.count().label("orders"),
                func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
            ).where(mine, window, Order.payment_status == PaymentStatus.REFUNDED.value)
        )
    ).one()

    # --- orders per local day -------------------------------------------------
    day_col = func.date_trunc("day", _local(Order.created_at))
    rows = (
        await db.execute(
            select(
                day_col.label("day"),
                func.count().label("orders"),
                func.coalesce(
                    func.sum(func.coalesce(Order.total_amount, 0)).filter(earning), 0
                ).label("revenue"),
            )
            .where(mine, window)
            .group_by(day_col)
            .order_by(day_col)
        )
    ).all()
    by_day = {r.day.date(): (r.orders, float(r.revenue)) for r in rows}

    # Gaps filled, so a quiet Tuesday is a trough rather than a missing bar - an
    # axis that skips it makes a bad week look like a steady one.
    start = (now + timedelta(hours=5, minutes=30)).date() - timedelta(days=days - 1)
    orders_by_day = [
        DayPoint(
            day=start + timedelta(days=offset),
            orders=by_day.get(start + timedelta(days=offset), (0, 0.0))[0],
            revenue=by_day.get(start + timedelta(days=offset), (0, 0.0))[1],
        )
        for offset in range(days)
    ]

    # --- busiest hours --------------------------------------------------------
    hour_col = func.extract("hour", _local(Order.created_at))
    hour_rows = (
        await db.execute(
            select(hour_col.label("hour"), func.count().label("orders"))
            .where(mine, window)
            .group_by(hour_col)
        )
    ).all()
    per_hour = {int(r.hour): r.orders for r in hour_rows}
    # All twenty-four, including the empty ones, so the shape of the day is
    # readable and the chart does not change width between refreshes.
    hours = [HourPoint(hour=h, orders=per_hour.get(h, 0)) for h in range(24)]

    # --- what actually sold ---------------------------------------------------
    #
    # Grouped on the snapshots rather than joined back to menu_items, so a dish
    # the stall has since renamed or deleted still appears under the name it was
    # sold as. That is also what makes this survive a menu reorganisation.
    from app.db.models.order import OrderItem

    dish_rows = (
        await db.execute(
            select(
                OrderItem.name_snapshot.label("name"),
                OrderItem.variant_name_snapshot.label("variant_name"),
                func.sum(OrderItem.quantity).label("quantity"),
                func.sum(OrderItem.price_snapshot * OrderItem.quantity).label("revenue"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .where(mine, window, earning)
            .group_by(OrderItem.name_snapshot, OrderItem.variant_name_snapshot)
            .order_by(func.sum(OrderItem.quantity).desc())
            .limit(12)
        )
    ).all()
    top_dishes = [
        TopDish(
            name=r.name,
            variant_name=r.variant_name,
            quantity=int(r.quantity),
            revenue=float(r.revenue or 0),
        )
        for r in dish_rows
    ]

    pending_price_changes = await db.scalar(
        select(func.count())
        .select_from(MenuItem)
        .where(MenuItem.vendor_id == vendor_id, MenuItem.pending_price.is_not(None))
    )

    return VendorAnalyticsOut(
        range_days=days,
        generated_at=now,
        totals=VendorTotals(
            orders=orders_total or 0,
            revenue=float(revenue_total or Decimal(0)),
            active_orders=active_orders or 0,
            refused_orders=refused_orders or 0,
            refused_value=float(refused_value or Decimal(0)),
            dine_in=MoneySplit(
                orders=split.dine_orders or 0,
                revenue=float(split.dine_revenue or 0),
            ),
            delivery=MoneySplit(
                orders=split.delivery_orders or 0,
                revenue=float(split.delivery_revenue or 0),
            ),
            cash=MoneySplit(
                orders=split.cash_orders or 0,
                revenue=float(split.cash_revenue or 0),
            ),
            prepaid=MoneySplit(
                orders=split.prepaid_orders or 0,
                revenue=float(split.prepaid_revenue or 0),
            ),
            dine_in_prepaid=MoneySplit(
                orders=split.dine_prepaid_orders or 0,
                revenue=float(split.dine_prepaid_revenue or 0),
            ),
            dine_in_cash=MoneySplit(
                orders=split.dine_cash_orders or 0,
                revenue=float(split.dine_cash_revenue or 0),
            ),
            delivery_prepaid=MoneySplit(
                orders=split.delivery_prepaid_orders or 0,
                revenue=float(split.delivery_prepaid_revenue or 0),
            ),
            delivery_cash=MoneySplit(
                orders=split.delivery_cash_orders or 0,
                revenue=float(split.delivery_cash_revenue or 0),
            ),
            outstanding=MoneySplit(orders=owed.orders or 0, revenue=float(owed.revenue or 0)),
            refunded=MoneySplit(
                orders=returned.orders or 0, revenue=float(returned.revenue or 0)
            ),
        ),
        orders_by_day=orders_by_day,
        hours=hours,
        top_dishes=top_dishes,
        pending_price_changes=pending_price_changes or 0,
    )
