import uuid
from decimal import Decimal

from pydantic import BaseModel, computed_field

from app.core.fields import Description, ImageUrl, Money, Name, SortOrder


class CategoryCreate(BaseModel):
    name: Name
    sort_order: SortOrder = 0


class CategoryUpdate(BaseModel):
    name: Name | None = None
    sort_order: SortOrder | None = None


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    sort_order: int

    model_config = {"from_attributes": True}


class ItemCreate(BaseModel):
    name: Name
    description: Description | None = None
    price: Money
    category_id: uuid.UUID | None = None
    image_url: ImageUrl | None = None


class ItemUpdate(BaseModel):
    """Everything about a dish except what it costs.

    `price` is deliberately absent. It used to be here, and update_item assigned
    the payload in a loop, which meant a merchant could set the live price
    directly - the thing the approval gate exists to prevent. Changing a price
    now goes through PUT /vendors/me/items/{id}/price, so "can a merchant write
    a price?" is answered by one handler whose only job is that, rather than by
    whether somebody remembered which fields are on this model.
    """

    name: Name | None = None
    description: Description | None = None
    category_id: uuid.UUID | None = None
    image_url: ImageUrl | None = None
    is_available: bool | None = None


class PriceUpdate(BaseModel):
    price: Money


class VariantCreate(BaseModel):
    name: Name
    price: Money
    sort_order: SortOrder = 0


class VariantUpdate(BaseModel):
    """As with ItemUpdate, no price. See PriceUpdate and the variant price route."""

    name: Name | None = None
    sort_order: SortOrder | None = None
    is_available: bool | None = None


class VariantOut(BaseModel):
    id: uuid.UUID
    name: str
    price: Decimal
    sort_order: int
    is_available: bool
    # Output only, on both this and ItemOut. pending_price appears on no input
    # schema anywhere, so a grep for it shows at a glance that a merchant can
    # read it and never write it.
    pending_price: Decimal | None
    price_awaiting_approval: bool

    model_config = {"from_attributes": True}


class ItemOut(BaseModel):
    id: uuid.UUID
    name: str
    # What the dish sells at today. A pending change does not touch it - that is
    # the whole of the enforcement, and why no read filters on pending_price.
    price: Decimal
    description: str | None
    category_id: uuid.UUID | None
    image_url: str | None
    is_available: bool

    variants: list[VariantOut] = []
    pending_price: Decimal | None = None
    price_awaiting_approval: bool = False

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def price_from(self) -> Decimal:
        """What to put under the dish name on a storefront.

        The item's own price when it has no sizes, otherwise the cheapest size a
        customer can actually buy - so a card reads "from 120" rather than
        quoting a number that belongs to nothing. Computed, never stored, so
        there is no second copy of a price to drift and no question about which
        one a pending change applies to.
        """
        sellable = [v.price for v in self.variants if v.is_available]
        return min(sellable) if sellable else self.price


class CategoryWithItems(CategoryOut):
    items: list[ItemOut]
