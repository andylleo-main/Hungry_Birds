"""What a student has, and what it would be worth on the cart in front of them.

Read-only. Nothing here mints or spends: earning happens when an order is
completed and spending happens inside place_order, both in the service module,
both inside the transaction that commits the order itself. An endpoint that
could move promotional credit on its own would be a way to print money with a
cURL command.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.config import Settings, get_settings
from app.core.deps import ORDERING_ROLES, require_role
from app.core.ratelimit import limit_by_user
from app.db.models.cashback import CashbackKind, CashbackReason
from app.db.models.coupon import Coupon, CouponRedemption
from app.db.models.order import FulfilmentType, Order
from app.db.models.user import User
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.cashback import service
from app.modules.orders.schemas import PaymentMethod
from app.modules.cashback.schemas import (
    CashbackOut,
    EntryOut,
    OrderCashbackOut,
    QuoteOut,
    WalletOut,
)

# How many movements the offers page gets. Enough to account for a balance
# several times over, bounded so the response stops growing with the account.
HISTORY_PAGE = 100

router = APIRouter(prefix="/cashback", tags=["cashback"])


@router.get(
    "",
    response_model=CashbackOut,
    dependencies=[Depends(limit_by_user("cashback_read", *limits.CASHBACK_READ))],
)
async def my_cashback(
    user: User = Depends(require_role(*ORDERING_ROLES)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CashbackOut:
    """Both balances and the movements behind them.

    The entries are returned alongside the balances rather than on a separate
    endpoint, because the offers page shows both together and a balance a student
    cannot account for is the thing that generates support messages.

    Newest first for display, though the balance walk needs them oldest first -
    hence the reversal here rather than a second query.
    """
    now = datetime.now(timezone.utc)
    # Three different slices, on purpose. `spendable` is the bounded window the
    # balance walk needs, `shown` is the newest page of history, and the lifetime
    # total is an aggregate - one list serving all three is what made this read
    # the entire ledger on every call.
    spendable = await service.entries_for(user.id, db, now=now)
    shown = await service.recent_entries(user.id, db, HISTORY_PAGE)
    balances = service.live_balances(spendable, now)

    # The stall and order number for each movement, in one query rather than one
    # per row, and as a join rather than a relationship: Order has no vendor
    # relationship, on purpose - every other path reaches the stall through the
    # vendor it is already scoped to.
    #
    # An entry whose order has since been deleted keeps its row with no name,
    # which the schema allows. The money is still the student's.
    order_ids = {e.order_id for e in shown if e.order_id is not None}
    named: dict[uuid.UUID, tuple[str, str]] = {}
    if order_ids:
        rows = await db.execute(
            select(Order.id, Order.order_number, Vendor.stall_name)
            .join(Vendor, Vendor.id == Order.vendor_id)
            .where(Order.id.in_(order_ids))
        )
        named = {row.id: (row.order_number, row.stall_name) for row in rows}

    coupon_orders = {e.order_id for e in shown if e.reason is CashbackReason.COUPON and e.order_id}
    codes: dict[uuid.UUID, str] = {}
    if coupon_orders:
        code_rows = await db.execute(
            select(CouponRedemption.order_id, Coupon.code)
            .join(Coupon, Coupon.id == CouponRedemption.coupon_id)
            .where(CouponRedemption.order_id.in_(coupon_orders))
        )
        codes = {r.order_id: r.code for r in code_rows}

    wallets = [
        WalletOut(
            kind=kind,
            balance=balances[kind],
            percent=service.rate_for(kind, settings, on=now).percent,
            cap=service.rate_for(kind, settings, on=now).cap,
            expires_next=service.next_expiry(spendable, kind, now),
        )
        for kind in CashbackKind
    ]

    return CashbackOut(
        wallets=wallets,
        entries=[
            EntryOut(
                id=e.id,
                kind=e.kind,
                amount=e.amount,
                reason=e.reason,
                order_id=e.order_id,
                stall_name=named[e.order_id][1] if e.order_id in named else None,
                order_number=named[e.order_id][0] if e.order_id in named else None,
                coupon_code=codes.get(e.order_id) if e.order_id else None,
                expires_at=e.expires_at,
                created_at=e.created_at,
            )
            # Already newest first from the query, so no reversal here.
            for e in shown
        ],
        saved_so_far=await service.saved_so_far_for(user.id, db),
    )


@router.get(
    "/quote",
    response_model=QuoteOut,
    dependencies=[Depends(limit_by_user("cashback_read", *limits.CASHBACK_READ))],
)
async def quote(
    vendor_id: uuid.UUID,
    subtotal: Decimal = Query(ge=0, le=100000, decimal_places=2),
    fulfilment_type: FulfilmentType = FulfilmentType.DINE_IN,
    payment_method: PaymentMethod = PaymentMethod.ONLINE,
    with_coupon: bool = False,
    user: User = Depends(require_role(*ORDERING_ROLES)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> QuoteOut:
    """Both halves of the choice: what spending would save, and what not would earn.

    `subtotal` is the client's figure and is used for nothing but this answer -
    it never reaches an order. The real redemption is computed again in
    place_order from the basket the server priced itself, so a client that lies
    here only lies to its own screen.

    Both paths call `spendable_on`, which is the point: the number a student is
    shown and the number they are charged are produced by the same function. The
    earning figure is the same arrangement one step further on - `would_earn` and
    `earned_on`, exactly as the completion path calls them - because a checkout
    that worked the rate out for itself would eventually promise cashback on a
    cash delivery, which earns nothing.

    The three new parameters all default to the combination that *does* earn, so
    a client that has never heard of them (the released bundle, when this ships)
    still gets a correct answer to the question it is actually asking. They are
    spelled with the same enums `OrderCreate` uses rather than as loose strings:
    one vocabulary for these facts, and a wrong value is a 422 rather than a
    silently-zero earning figure.
    """
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None or not vendor.is_approved:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")

    now = datetime.now(timezone.utc)
    kind = service.kind_for(vendor, settings)
    rate = service.rate_for(kind, settings, on=now)
    entries = await service.entries_for(user.id, db, now=now)
    balance = service.live_balances(entries, now)[kind]
    redeemable = service.spendable_on(subtotal, balance, rate)

    # "If nothing is applied" - so a redemption the student has not committed to
    # is not counted against it. `with_coupon` is the one discount that can
    # already be on the cart at the moment this is asked, since a coupon is
    # applied by typing it and cashback only by choosing between these two.
    earning = (
        service.earned_on(subtotal, rate)
        if service.would_earn(
            fulfilment_type=fulfilment_type,
            payment_method=payment_method.value,
            discounted=with_coupon,
        )
        else Decimal("0")
    )

    return QuoteOut(
        kind=kind,
        balance=balance,
        redeemable=redeemable,
        payable=Decimal(subtotal) - redeemable,
        percent=rate.percent,
        earning=earning,
    )


@router.get(
    "/orders/{order_id}",
    response_model=OrderCashbackOut,
    dependencies=[Depends(limit_by_user("cashback_read", *limits.CASHBACK_READ))],
)
async def order_cashback(
    order_id: uuid.UUID,
    user: User = Depends(require_role(*ORDERING_ROLES)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> OrderCashbackOut:
    """What this order credits once completed, or has already credited."""
    order = await db.get(Order, order_id)
    if order is None or order.customer_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    amount, credited, source = await service.expected_for(order, db, settings)
    return OrderCashbackOut(amount=amount, credited=credited, source=source)
