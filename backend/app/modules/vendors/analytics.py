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
from app.db.models.order import Order, OrderStatus
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
        ),
        orders_by_day=orders_by_day,
        hours=hours,
        top_dishes=top_dishes,
        pending_price_changes=pending_price_changes or 0,
    )
