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
    locations: list[LocationOut]


class FulfilmentUpdate(BaseModel):
    dine_in_enabled: bool
    delivery_enabled: bool
    # The codes that should end up ON. A full replacement, so whatever is absent
    # is switched off; the length cap is the size of the catalogue, since
    # repeating a code is harmless but sending thousands is not.
    enabled_locations: list[str] = Field(max_length=len(DELIVERY_LOCATIONS))
