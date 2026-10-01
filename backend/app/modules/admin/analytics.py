"""Aggregate numbers for the admin dashboard.

All of this is computed in Postgres rather than by pulling rows into Python.
At thirty stalls that hardly matters today, but a dashboard that loads every
order to count them is the kind of thing that works fine until the day it
doesn't, and the SQL is no harder to read.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.order import Order, OrderStatus
from app.db.models.payment import PaymentStatus
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor

# Which orders count as money taken.
#
# Listed explicitly rather than derived as "every status except cancelled".
# That comprehension had two problems. It counted REJECTED orders - food the
# stall refused to make, which is revenue nobody ever received - so every
# figure on this page was overstated by the value of the rejections. And being
# a comprehension over the enum, it silently swallowed any status added later:
# a new one would have been booked as income the day it shipped, with nothing in
# the diff to suggest it. An explicit list means adding a status is a decision
# somebody has to make here.
EARNING_STATUSES = [
    OrderStatus.PLACED,
    OrderStatus.ACCEPTED,
    OrderStatus.PREPARING,
    OrderStatus.READY,
    OrderStatus.OUT_FOR_DELIVERY,
    OrderStatus.COMPLETED,
]

# Orders somebody is still working on - what an admin wants at a glance.
#
# Listed here rather than inline in the query, and next to EARNING_STATUSES, so
# the two are read together. out_for_delivery was missing after riders shipped,
# which left an order with a rider on the way counted as neither active nor
# finished. awaiting_payment is deliberately absent: nobody is working on an
# order nobody has paid for, and no stall has even seen it.
ACTIVE_STATUSES = [
    OrderStatus.PLACED,
    OrderStatus.ACCEPTED,
    OrderStatus.PREPARING,
    OrderStatus.READY,
    OrderStatus.OUT_FOR_DELIVERY,
]


class Totals(BaseModel):
    orders: int
    revenue: float
    customers: int
    vendors: int
    pending_vendors: int
    # Orders not yet handed over - what an admin actually wants at a glance.
    active_orders: int


class DayPoint(BaseModel):
    day: date
    orders: int
    revenue: float


class StatusSlice(BaseModel):
    status: OrderStatus
    count: int


class TopVendor(BaseModel):
    vendor_id: uuid.UUID
    stall_name: str
    orders: int
    revenue: float


class AnalyticsOut(BaseModel):
    range_days: int
    generated_at: datetime
    totals: Totals
    orders_by_day: list[DayPoint]
    status_breakdown: list[StatusSlice]
    top_vendors: list[TopVendor]


async def build_analytics(days: int, db: AsyncSession) -> AnalyticsOut:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    # Paid *and* not rejected. Once money moves online, "an order exists" and
    # "we were paid" stop being the same statement: an unpaid checkout is not
    # revenue, and a refunded one is revenue that went back.
    earning = Order.status.in_(EARNING_STATUSES) & (
        Order.payment_status == PaymentStatus.PAID.value
    )

    # --- headline totals ----------------------------------------------------
    orders_total = await db.scalar(
        select(func.count()).select_from(Order).where(Order.created_at >= since)
    )
    revenue_total = await db.scalar(
        select(func.coalesce(func.sum(Order.total_amount), 0)).where(
            Order.created_at >= since, earning
        )
    )
    customers = await db.scalar(
        select(func.count()).select_from(User).where(User.role == UserRole.CUSTOMER)
    )
    vendors = await db.scalar(
        select(func.count()).select_from(Vendor).where(Vendor.is_approved.is_(True))
    )
    pending_vendors = await db.scalar(
        select(func.count()).select_from(Vendor).where(Vendor.is_approved.is_(False))
    )
    active_orders = await db.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.status.in_(ACTIVE_STATUSES))
    )

    # --- orders per day -----------------------------------------------------
    day_col = func.date_trunc("day", Order.created_at)
    rows = (
        await db.execute(
            select(
                day_col.label("day"),
                func.count().label("orders"),
                func.coalesce(
                    func.sum(func.coalesce(Order.total_amount, 0)).filter(earning), 0
                ).label("revenue"),
            )
            .where(Order.created_at >= since)
            .group_by(day_col)
            .order_by(day_col)
        )
    ).all()
    by_day = {r.day.date(): (r.orders, float(r.revenue)) for r in rows}

    # Fill the gaps. A line chart that silently skips quiet days compresses the
    # axis and makes a flat week look like steady trade.
    start = (now - timedelta(days=days - 1)).date()
    orders_by_day = []
    for offset in range(days):
        d = start + timedelta(days=offset)
        count, revenue = by_day.get(d, (0, 0.0))
        orders_by_day.append(DayPoint(day=d, orders=count, revenue=revenue))

    # --- status mix ---------------------------------------------------------
    status_rows = (
        await db.execute(
            select(Order.status, func.count().label("count"))
            .where(Order.created_at >= since)
            .group_by(Order.status)
        )
    ).all()
    counts = {r.status: r.count for r in status_rows}
    # Every status present, including the zeroes, so the legend doesn't change
    # shape between refreshes.
    status_breakdown = [StatusSlice(status=s, count=counts.get(s, 0)) for s in OrderStatus]

    # --- busiest stalls -----------------------------------------------------
    top_rows = (
        await db.execute(
            select(
                Vendor.id,
                Vendor.stall_name,
                func.count(Order.id).label("orders"),
                func.coalesce(
                    func.sum(func.coalesce(Order.total_amount, 0)).filter(earning), 0
                ).label("revenue"),
            )
            .join(Order, Order.vendor_id == Vendor.id)
            .where(Order.created_at >= since)
            .group_by(Vendor.id, Vendor.stall_name)
            .order_by(func.count(Order.id).desc())
            .limit(8)
        )
    ).all()

    return AnalyticsOut(
        range_days=days,
        generated_at=now,
        totals=Totals(
            orders=orders_total or 0,
            revenue=float(revenue_total or 0),
            customers=customers or 0,
            vendors=vendors or 0,
            pending_vendors=pending_vendors or 0,
            active_orders=active_orders or 0,
        ),
        orders_by_day=orders_by_day,
        status_breakdown=status_breakdown,
        top_vendors=[
            TopVendor(
                vendor_id=r.id,
                stall_name=r.stall_name,
                orders=r.orders,
                revenue=float(r.revenue),
            )
            for r in top_rows
        ],
    )
