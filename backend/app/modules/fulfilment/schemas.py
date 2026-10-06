from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.locations import DELIVERY_LOCATIONS


class LocationOut(BaseModel):
    code: str
    label: str
    enabled: bool


class FulfilmentOut(BaseModel):
    """What the merchant's settings screen renders.

    Every location in the catalogue is listed with its state, not just the
    enabled ones, because the screen is a list of switches - it needs the ones
    that are off in order to draw them.
    """

    dine_in_enabled: bool
    delivery_enabled: bool
    # Delivery only, and 0 means none. There is no dine-in equivalent: nobody
    # is sent anywhere for an order eaten at the counter.
    min_delivery_order: Decimal
    locations: list[LocationOut]


class FulfilmentUpdate(BaseModel):
    dine_in_enabled: bool
    delivery_enabled: bool
    # Optional, unlike the two booleans, and omitting it leaves the stall's
    # current figure alone. A released APK does not send this field - it was
    # built before the field existed - and making it required would mean an old
    # merchant app got a 422 trying to switch delivery off, which is a worse
    # failure than not being able to edit a minimum it cannot see.
    #
    # Capped rather than open-ended, because the only effect of a very large
    # minimum is a stall that silently takes no deliveries at all, and there is
    # already a switch for that. Zero is allowed and means no minimum.
    min_delivery_order: Decimal | None = Field(default=None, ge=0, le=10000, decimal_places=2)
    # The codes that should end up ON. A full replacement, so whatever is absent
    # is switched off; the length cap is the size of the catalogue, since
    # repeating a code is harmless but sending thousands is not.
    enabled_locations: list[str] = Field(max_length=len(DELIVERY_LOCATIONS))
