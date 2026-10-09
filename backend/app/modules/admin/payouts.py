"""Weekly settlement per stall: what came in online, what is already in the till.

Weeks run Monday to Sunday on the IST calendar, the same calendar the merchant
analytics and token counter use. An order belongs to the week it was placed in.

Only earning, paid orders count, the same predicate as every takings figure, so a
week's `order_value` matches the finances screen for the same dates.

The money splits three ways and they always sum back to `order_value`:
  prepaid_online + cash_in_hand + discounts == order_value
- cash_in_hand is what the stall physically collected (a cash pay-on-delivery
  order's amount_due). A doorstep UPI scan is prepaid, as on the merchant app.
- discounts are cashback and coupons, which Hungry Birds funds, not the stall.
So what Hungry Birds owes the stall is order_value - cash_in_hand.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.cashback import CashbackEntry, CashbackReason
from app.db.models.order import Order
from app.db.models.payment import PaymentStatus
from app.db.models.vendor import Vendor
from app.modules.admin.analytics import EARNING_STATUSES

IST_OFFSET = timedelta(hours=5, minutes=30)


class StallPayout(BaseModel):
    vendor_id: uuid.UUID
    stall_name: str
    orders: int
    order_value: float
    prepaid_online: float
    cash_in_hand: float
    discounts: float
    owed_to_stall: float


class PayoutWeek(BaseModel):
    week_start: date
    week_end: date
    stalls: list[StallPayout]
    totals: StallPayout | None


class PayoutsOut(BaseModel):
    generated_at: datetime
    weeks: list[PayoutWeek]


def _row(vendor_id, name, orders, value, cash_due, discounts) -> StallPayout:
    value, cash_due, discounts = float(value or 0), float(cash_due or 0), float(discounts or 0)
    return StallPayout(
        vendor_id=vendor_id,
        stall_name=name,
        orders=orders or 0,
        order_value=value,
        prepaid_online=round(value - cash_due - discounts, 2),
        cash_in_hand=cash_due,
        discounts=discounts,
        owed_to_stall=round(value - cash_due, 2),
    )


async def build_payouts(weeks: int, vendor_id: uuid.UUID | None, db: AsyncSession) -> PayoutsOut:
    now = datetime.now(timezone.utc)
    today = (now + IST_OFFSET).date()
    this_monday = today - timedelta(days=today.weekday())
    first_monday = this_monday - timedelta(weeks=weeks - 1)
    since = datetime.combine(first_monday, datetime.min.time(), tzinfo=timezone.utc) - IST_OFFSET

    week_col = func.date_trunc("week", func.timezone("Asia/Kolkata", Order.created_at))
    discount = Order.cashback_applied + Order.coupon_discount
    in_cash = (Order.payment_method == "cod") & (func.coalesce(Order.collected_via, "") == "cash")

    where = [
        Order.created_at >= since,
        Order.status.in_(EARNING_STATUSES),
        Order.payment_status == PaymentStatus.PAID.value,
    ]
    if vendor_id is not None:
        where.append(Order.vendor_id == vendor_id)

    rows = (
        await db.execute(
            select(
                week_col.label("week"),
                Vendor.id,
                Vendor.stall_name,
                func.count().label("orders"),
                func.coalesce(func.sum(Order.total_amount), 0).label("value"),
                func.coalesce(
                    func.sum(Order.total_amount - discount).filter(in_cash), 0
                ).label("cash_due"),
                func.coalesce(func.sum(discount), 0).label("discounts"),
            )
            .join(Vendor, Vendor.id == Order.vendor_id)
            .where(*where)
            .group_by(week_col, Vendor.id, Vendor.stall_name)
        )
    ).all()

    by_week: dict[date, list[StallPayout]] = {}
    for r in rows:
        by_week.setdefault(r.week.date(), []).append(
            _row(r.id, r.stall_name, r.orders, r.value, r.cash_due, r.discounts)
        )

    out = []
    for offset in range(weeks):
        start = this_monday - timedelta(weeks=offset)
        stalls = sorted(by_week.get(start, []), key=lambda s: -s.order_value)
        totals = (
            StallPayout(
                vendor_id=uuid.UUID(int=0),
                stall_name="All stalls",
                orders=sum(s.orders for s in stalls),
                order_value=round(sum(s.order_value for s in stalls), 2),
                prepaid_online=round(sum(s.prepaid_online for s in stalls), 2),
                cash_in_hand=round(sum(s.cash_in_hand for s in stalls), 2),
                discounts=round(sum(s.discounts for s in stalls), 2),
                owed_to_stall=round(sum(s.owed_to_stall for s in stalls), 2),
            )
            if stalls
            else None
        )
        out.append(PayoutWeek(week_start=start, week_end=start + timedelta(days=6), stalls=stalls, totals=totals))
    return PayoutsOut(generated_at=now, weeks=out)


class StallCashback(BaseModel):
    vendor_id: uuid.UUID
    stall_name: str
    orders: int
    earned: float
    from_coupons: float
    total: float


class CashbackWeek(BaseModel):
    week_start: date
    week_end: date
    stalls: list[StallCashback]
    totals: StallCashback | None


class CashbackReportOut(BaseModel):
    generated_at: datetime
    weeks: list[CashbackWeek]


async def build_cashback_report(weeks: int, db: AsyncSession) -> CashbackReportOut:
    """Cashback credited per stall per IST week, split earned vs from coupons.

    A credit belongs to the week it landed in the wallet (order completion).
    """
    now = datetime.now(timezone.utc)
    today = (now + IST_OFFSET).date()
    this_monday = today - timedelta(days=today.weekday())
    first_monday = this_monday - timedelta(weeks=weeks - 1)
    since = datetime.combine(first_monday, datetime.min.time(), tzinfo=timezone.utc) - IST_OFFSET

    week_col = func.date_trunc("week", func.timezone("Asia/Kolkata", CashbackEntry.created_at))
    is_earned = CashbackEntry.reason == CashbackReason.EARNED
    is_coupon = CashbackEntry.reason == CashbackReason.COUPON
    rows = (
        await db.execute(
            select(
                week_col.label("week"),
                Vendor.id,
                Vendor.stall_name,
                func.count(func.distinct(CashbackEntry.order_id)).label("orders"),
                func.coalesce(func.sum(CashbackEntry.amount).filter(is_earned), 0).label("earned"),
                func.coalesce(func.sum(CashbackEntry.amount).filter(is_coupon), 0).label("coupons"),
            )
            .join(Order, Order.id == CashbackEntry.order_id)
            .join(Vendor, Vendor.id == Order.vendor_id)
            .where(
                CashbackEntry.created_at >= since,
                CashbackEntry.reason.in_([CashbackReason.EARNED, CashbackReason.COUPON]),
            )
            .group_by(week_col, Vendor.id, Vendor.stall_name)
        )
    ).all()

    by_week: dict[date, list[StallCashback]] = {}
    for r in rows:
        earned, coupons = float(r.earned), float(r.coupons)
        by_week.setdefault(r.week.date(), []).append(
            StallCashback(
                vendor_id=r.id,
                stall_name=r.stall_name,
                orders=r.orders,
                earned=earned,
                from_coupons=coupons,
                total=round(earned + coupons, 2),
            )
        )

    out = []
    for offset in range(weeks):
        start = this_monday - timedelta(weeks=offset)
        stalls = sorted(by_week.get(start, []), key=lambda s: -s.total)
        totals = (
            StallCashback(
                vendor_id=uuid.UUID(int=0),
                stall_name="All stalls",
                orders=sum(s.orders for s in stalls),
                earned=round(sum(s.earned for s in stalls), 2),
                from_coupons=round(sum(s.from_coupons for s in stalls), 2),
                total=round(sum(s.total for s in stalls), 2),
            )
            if stalls
            else None
        )
        out.append(CashbackWeek(week_start=start, week_end=start + timedelta(days=6), stalls=stalls, totals=totals))
    return CashbackReportOut(generated_at=now, weeks=out)
