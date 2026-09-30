from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.locations import DELIVERY_LOCATIONS
from app.core.ratelimit import limit_by_user
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.fulfilment.schemas import FulfilmentOut, FulfilmentUpdate, LocationOut
from app.modules.fulfilment.service import disabled_codes, set_enabled_codes
from app.modules.vendors.deps import get_own_vendor

# Owns a slice of the vendor's own namespace, the same way modules/menu does.
router = APIRouter(prefix="/vendors/me/fulfilment", tags=["fulfilment"])


async def _current(vendor: Vendor, db: AsyncSession) -> FulfilmentOut:
    disabled = await disabled_codes(vendor.id, db)
    return FulfilmentOut(
        dine_in_enabled=vendor.dine_in_enabled,
        delivery_enabled=vendor.delivery_enabled,
        locations=[
            LocationOut(code=code, label=label, enabled=code not in disabled)
            for code, label in DELIVERY_LOCATIONS.items()
        ],
    )


@router.get(
    "",
    response_model=FulfilmentOut,
    dependencies=[Depends(limit_by_user("fulfilment_read", *limits.FULFILMENT_READ))],
)
async def read_fulfilment(
    vendor: Vendor = Depends(get_own_vendor), db: AsyncSession = Depends(get_db)
) -> FulfilmentOut:
    return await _current(vendor, db)


@router.put(
    "",
    response_model=FulfilmentOut,
    dependencies=[Depends(limit_by_user("fulfilment_write", *limits.FULFILMENT_WRITE))],
)
async def update_fulfilment(
    payload: FulfilmentUpdate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> FulfilmentOut:
    """Set how this stall hands food over.

    Deliberately its own endpoint rather than more fields on PATCH /vendors/me:
    that handler assigns whatever the payload contains in a loop, so every field
    added to it becomes self-writable with no per-field check. Settings that
    decide which orders a stall can receive are worth a handler that names them.
    """
    if not payload.dine_in_enabled and not payload.delivery_enabled:
        # Allowing this would leave a stall that reads as open but rejects every
        # order, which is a confusing way to be closed. There is already a
        # switch for being closed.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Keep dine-in or delivery switched on. To stop taking orders, close the stall instead.",
        )

    await set_enabled_codes(vendor.id, set(payload.enabled_locations), db)
    vendor.dine_in_enabled = payload.dine_in_enabled
    vendor.delivery_enabled = payload.delivery_enabled
    await db.commit()
    await db.refresh(vendor)
    return await _current(vendor, db)
