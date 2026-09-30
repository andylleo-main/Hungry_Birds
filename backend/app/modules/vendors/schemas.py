import uuid

from pydantic import BaseModel

from app.core.fields import Description, ImageUrl, Name
from app.modules.fulfilment.schemas import LocationOut
from app.modules.menu.schemas import CategoryWithItems, ItemOut


class VendorApply(BaseModel):
    stall_name: Name
    description: Description | None = None


class VendorUpdate(BaseModel):
    stall_name: Name | None = None
    description: Description | None = None
    cover_image_url: ImageUrl | None = None
    is_open: bool | None = None


class VendorOut(BaseModel):
    id: uuid.UUID
    stall_name: str
    description: str | None
    cover_image_url: str | None
    is_approved: bool
    is_open: bool
    # Flat booleans, so a stall card can say "delivers" without loading a
    # location list for every stall on the discover page.
    dine_in_enabled: bool
    delivery_enabled: bool

    model_config = {"from_attributes": True}


class VendorDetailOut(VendorOut):
    categories: list[CategoryWithItems]
    uncategorized_items: list[ItemOut]
    # Only the locations this stall actually delivers to, so checkout can render
    # the choice directly. A customer has no use for the ones it switched off,
    # and listing them would invite a selection that is rejected on submit.
    delivery_locations: list[LocationOut]
