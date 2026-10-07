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
from app.db.models.cashback import CashbackKind
from app.db.models.order import Order
from app.db.models.user import User
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.cashback import service
from app.modules.cashback.schemas import CashbackOut, EntryOut, QuoteOut, WalletOut

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
    entries = await service.entries_for(user.id, db)
    now = datetime.now(timezone.utc)
    balances = service.live_balances(entries, now)

    # The stall and order number for each movement, in one query rather than one
    # per row, and as a join rather than a relationship: Order has no vendor
    # relationship, on purpose - every other path reaches the stall through the
    # vendor it is already scoped to.
    #
    # An entry whose order has since been deleted keeps its row with no name,
    # which the schema allows. The money is still the student's.
    order_ids = {e.order_id for e in entries if e.order_id is not None}
    named: dict[uuid.UUID, tuple[str, str]] = {}
    if order_ids:
        rows = await db.execute(
            select(Order.id, Order.order_number, Vendor.stall_name)
            .join(Vendor, Vendor.id == Order.vendor_id)
            .where(Order.id.in_(order_ids))
        )
        named = {row.id: (row.order_number, row.stall_name) for row in rows}

    wallets = [
        WalletOut(
            kind=kind,
            balance=balances[kind],
            percent=service.rate_for(kind, settings, on=now).percent,
            cap=service.rate_for(kind, settings, on=now).cap,
            expires_next=service.next_expiry(entries, kind, now),
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
                expires_at=e.expires_at,
                created_at=e.created_at,
            )
            for e in reversed(entries)
        ],
    )


@router.get(
    "/quote",
    response_model=QuoteOut,
    dependencies=[Depends(limit_by_user("cashback_read", *limits.CASHBACK_READ))],
)
async def quote(
    vendor_id: uuid.UUID,
    subtotal: Decimal = Query(ge=0, le=100000, decimal_places=2),
    user: User = Depends(require_role(*ORDERING_ROLES)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> QuoteOut:
    """What would come off a cart of this size at this stall.

    `subtotal` is the client's figure and is used for nothing but this answer -
    it never reaches an order. The real redemption is computed again in
    place_order from the basket the server priced itself, so a client that lies
    here only lies to its own screen.

    Both paths call `spendable_on`, which is the point: the number a student is
    shown and the number they are charged are produced by the same function.
    """
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None or not vendor.is_approved:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")

    now = datetime.now(timezone.utc)
    kind = service.kind_for(vendor, settings)
    rate = service.rate_for(kind, settings, on=now)
    entries = await service.entries_for(user.id, db)
    balance = service.live_balances(entries, now)[kind]
    redeemable = service.spendable_on(subtotal, balance, rate)

    return QuoteOut(
        kind=kind,
        balance=balance,
        redeemable=redeemable,
        payable=Decimal(subtotal) - redeemable,
        percent=rate.percent,
    )
