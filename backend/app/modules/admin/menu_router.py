"""The admin's queue of price changes waiting on a decision.

Mirrors the vendor-approval pattern next door: the gate is on the router, the
queue is a filter over the rows themselves rather than a separate request table,
and approving is a single field write.

One resource keyed by target type rather than two parallel route pairs, because
an item's price and a size's price are the same decision - "may this stall
charge this?" - and an admin looking at the queue should not have to know which
shape they are looking at before they can act on it.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import limits
from app.core.deps import require_role
from app.core.ratelimit import limit_by_user
from app.db.models.menu import MenuItem, MenuItemVariant
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.menu.service import apply_price_decision

router = APIRouter(
    prefix="/admin/menu", tags=["admin"], dependencies=[Depends(require_role(UserRole.ADMIN))]
)


class PendingPriceOut(BaseModel):
    """One price change, whichever kind of thing it belongs to."""

    target: str  # "item" or "variant"
    target_id: uuid.UUID
    vendor_id: uuid.UUID
    stall_name: str
    item_name: str
    variant_name: str | None
    current_price: Decimal
    pending_price: Decimal
    # Worked out here rather than in the browser, because sorting by "biggest
    # jump" is the only ordering an admin actually wants and it should not
    # depend on which client is asking.
    pct_change: float
    requested_at: datetime | None


def _pct(old: Decimal, new: Decimal) -> float:
    if not old:
        return 0.0
    return round(float((new - old) / old * 100), 1)


@router.get(
    "/price-changes",
    response_model=list[PendingPriceOut],
    dependencies=[Depends(limit_by_user("admin_read", *limits.ADMIN_READ))],
)
async def list_price_changes(
    vendor_id: uuid.UUID | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[PendingPriceOut]:
    """Everything waiting on a decision, oldest first.

    Oldest first, like list_vendors_for_admin's order_by(created_at): the
    merchant who has been waiting longest is the one being hurt by the wait.

    Two queries unioned in Python rather than a SQL UNION. This is tens of rows
    on a campus with thirty stalls, not a reporting workload, and the two shapes
    need different joins to reach a stall name.
    """
    items_q = (
        select(MenuItem, Vendor.stall_name)
        .join(Vendor, Vendor.id == MenuItem.vendor_id)
        .where(MenuItem.pending_price.is_not(None))
    )
    variants_q = (
        select(MenuItemVariant, MenuItem, Vendor.stall_name)
        .join(MenuItem, MenuItem.id == MenuItemVariant.item_id)
        .join(Vendor, Vendor.id == MenuItem.vendor_id)
        .where(MenuItemVariant.pending_price.is_not(None))
    )
    if vendor_id is not None:
        items_q = items_q.where(MenuItem.vendor_id == vendor_id)
        variants_q = variants_q.where(MenuItem.vendor_id == vendor_id)

    pending: list[PendingPriceOut] = []

    for item, stall_name in (await db.execute(items_q)).all():
        pending.append(
            PendingPriceOut(
                target="item",
                target_id=item.id,
                vendor_id=item.vendor_id,
                stall_name=stall_name,
                item_name=item.name,
                variant_name=None,
                current_price=item.price,
                pending_price=item.pending_price,
                pct_change=_pct(item.price, item.pending_price),
                requested_at=item.pending_price_at,
            )
        )

    for variant, item, stall_name in (await db.execute(variants_q)).all():
        pending.append(
            PendingPriceOut(
                target="variant",
                target_id=variant.id,
                vendor_id=item.vendor_id,
                stall_name=stall_name,
                item_name=item.name,
                variant_name=variant.name,
                current_price=variant.price,
                pending_price=variant.pending_price,
                pct_change=_pct(variant.price, variant.pending_price),
                requested_at=variant.pending_price_at,
            )
        )

    pending.sort(key=lambda p: (p.requested_at is None, p.requested_at))
    return pending[:limit]


async def _load_target(target: str, target_id: uuid.UUID, db: AsyncSession):
    """The row, its stall, and the name to record against the decision."""
    if target == "item":
        result = await db.execute(
            select(MenuItem).where(MenuItem.id == target_id).options(selectinload(MenuItem.variants))
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        return item, item.vendor_id, item.name

    if target == "variant":
        result = await db.execute(
            select(MenuItemVariant, MenuItem)
            .join(MenuItem, MenuItem.id == MenuItemVariant.item_id)
            .where(MenuItemVariant.id == target_id)
        )
        row = result.first()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Size not found")
        variant, item = row
        return variant, item.vendor_id, f"{item.name} - {variant.name}"

    raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown target")


async def _decide(
    target: str, target_id: uuid.UUID, approve: bool, admin: User, db: AsyncSession
) -> dict:
    row, vendor_id, name = await _load_target(target, target_id, db)
    if row.pending_price is None:
        # The admin panel's list can be stale - somebody else may have decided,
        # or the merchant may have withdrawn it. Saying so beats silently
        # approving a price that is no longer proposed.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No price change is waiting on this")

    apply_price_decision(
        row, approve=approve, db=db, vendor_id=vendor_id, name=name, admin_id=admin.id
    )
    await db.commit()
    await db.refresh(row)
    return {"target": target, "target_id": str(target_id), "price": str(row.price)}


@router.post(
    "/price-changes/{target}/{target_id}/approve",
    dependencies=[Depends(limit_by_user("admin_write", *limits.ADMIN_WRITE))],
)
async def approve_price_change(
    target: str,
    target_id: uuid.UUID,
    admin: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The only thing in the codebase that writes a live price after creation."""
    return await _decide(target, target_id, True, admin, db)


@router.post(
    "/price-changes/{target}/{target_id}/reject",
    dependencies=[Depends(limit_by_user("admin_write", *limits.ADMIN_WRITE))],
)
async def reject_price_change(
    target: str,
    target_id: uuid.UUID,
    admin: User = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _decide(target, target_id, False, admin, db)
