"""Reading and enforcing a stall's fulfilment settings.

Kept out of the router because two very different callers need the same answer:
the merchant editing their own settings, and place_order deciding whether an
incoming order is one this stall will actually accept.
"""

import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.locations import DELIVERY_LOCATIONS, is_known_location
from app.db.models.order import FulfilmentType
from app.db.models.vendor import Vendor, VendorDisabledLocation


async def disabled_codes(vendor_id: uuid.UUID, db: AsyncSession) -> set[str]:
    result = await db.execute(
        select(VendorDisabledLocation.code).where(VendorDisabledLocation.vendor_id == vendor_id)
    )
    return set(result.scalars().all())


async def enabled_codes(vendor_id: uuid.UUID, db: AsyncSession) -> list[str]:
    """The locations this stall delivers to, in catalogue order.

    Derived by subtraction, which is what makes every location on by default.
    A code held in the disabled table that is no longer in the catalogue is
    ignored rather than raising - see app.core.locations.
    """
    disabled = await disabled_codes(vendor_id, db)
    return [code for code in DELIVERY_LOCATIONS if code not in disabled]


async def set_enabled_codes(
    vendor_id: uuid.UUID, enabled: set[str], db: AsyncSession
) -> None:
    """Replace this stall's location choices.

    Written as a full replacement rather than a diff so the merchant's screen is
    the whole truth and two devices editing at once cannot interleave into a
    state neither of them chose.
    """
    unknown = sorted(code for code in enabled if not is_known_location(code))
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown delivery location(s): {', '.join(unknown)}",
        )

    existing = await disabled_codes(vendor_id, db)
    wanted_disabled = {code for code in DELIVERY_LOCATIONS if code not in enabled}

    for code in wanted_disabled - existing:
        db.add(VendorDisabledLocation(vendor_id=vendor_id, code=code))

    to_reenable = existing - wanted_disabled
    if to_reenable:
        rows = await db.execute(
            select(VendorDisabledLocation).where(
                VendorDisabledLocation.vendor_id == vendor_id,
                VendorDisabledLocation.code.in_(to_reenable),
            )
        )
        for row in rows.scalars().all():
            await db.delete(row)


async def assert_order_fulfilment(
    vendor: Vendor,
    fulfilment_type: FulfilmentType,
    delivery_location: str | None,
    db: AsyncSession,
) -> None:
    """Refuse an order the stall has said it will not fulfil.

    The schema already guarantees the shape - a delivery carries a location, a
    dine-in does not. What can only be checked here is whether *this* stall
    accepts that mode and that place, which is data rather than structure.
    """
    if fulfilment_type is FulfilmentType.DINE_IN:
        if not vendor.dine_in_enabled:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This stall is not taking dine-in orders right now"
            )
        return

    if not vendor.delivery_enabled:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This stall is not delivering right now"
        )

    # Unknown codes are rejected here as well as in set_enabled_codes, because a
    # stall that never touched its settings has no rows to check the code
    # against - an unrecognised place would otherwise count as enabled.
    if not is_known_location(delivery_location or ""):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown delivery location")

    if delivery_location in await disabled_codes(vendor.id, db):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This stall does not deliver to that location"
        )


def assert_meets_minimum(
    vendor: Vendor, fulfilment_type: FulfilmentType, total: Decimal
) -> None:
    """Refuse a delivery smaller than this stall will cook for.

    Separate from assert_order_fulfilment, and called from a different place,
    because it needs something that function cannot have: the basket's total.
    The total is only known after every line has been priced off the rows the
    server read - the payload's own figures are never trusted - so the check has
    to happen after that, not alongside the mode and location checks that run
    before anything is priced.

    Dine-in is exempt. The minimum exists because a delivery costs the stall a
    trip, and there is no trip to the counter.
    """
    if fulfilment_type is not FulfilmentType.DELIVERY:
        return
    minimum = vendor.min_delivery_order or Decimal(0)
    if minimum <= 0 or total >= minimum:
        return
    short = minimum - total
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        f"{vendor.stall_name} delivers orders of ₹{minimum:.0f} or more. "
        f"Add ₹{short:.0f} more, or eat at the stall instead.",
    )
