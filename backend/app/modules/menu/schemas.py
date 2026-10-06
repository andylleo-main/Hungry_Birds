import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, computed_field

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


# Roughly how long a dish takes. Bounded at both ends: zero would mean a student
# is told their food is ready before it is started, and four hours is longer than
# anybody waits for campus food - a stall that types 999 by accident should not
# tell somebody to come back tomorrow.
PrepMinutes = Annotated[int, Field(ge=1, le=240)]


class ItemCreate(BaseModel):
    name: Name
    description: Description | None = None
    price: Money
    category_id: uuid.UUID | None = None
    image_url: ImageUrl | None = None
    prep_minutes: PrepMinutes | None = None


class ItemUpdate(BaseModel):
    """Everything about a dish except what it costs.

    `price` is deliberately absent. It used to be here, and update_item assigned
    the payload in a loop, which meant a merchant could set the live price
    directly - the thing the approval gate exists to prevent. Changing a price
    now goes through PUT /vendors/me/items/{id}/price, so "can a merchant write
    a price?" is answered by one handler whose only job is that, rather than by
    whether somebody remembered which fields are on this model.

    `prep_minutes` *is* here, and the asymmetry is the point. A wrong prep time
    costs a few minutes of goodwill and the merchant fixes it themselves; a wrong
    price costs money. Only one of those is worth an admin standing in the way.
    """

    # Rejects unknown fields rather than ignoring them, which is Pydantic's
    # default and was the wrong one here. A merchant APK built before price moved
    # to its own route still sends `price` on every save; ignoring it meant a 200,
    # a "saved" toast, and a price that silently did not move. A 422 naming the
    # field is a worse-looking answer and a far better one - the app already
    # surfaces the message, and an old build fails loudly instead of lying.
    model_config = {"extra": "forbid"}

    name: Name | None = None
    description: Description | None = None
    category_id: uuid.UUID | None = None
    image_url: ImageUrl | None = None
    is_available: bool | None = None
    prep_minutes: PrepMinutes | None = None


class PriceUpdate(BaseModel):
    price: Money


class VariantCreate(BaseModel):
    name: Name
    price: Money
    sort_order: SortOrder = 0


class VariantUpdate(BaseModel):
    """As with ItemUpdate, no price. See PriceUpdate and the variant price route."""

    model_config = {"extra": "forbid"}

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
    # Null means the stall has not said. Clients show nothing rather than a
    # guess, which is why this is not defaulted to a number anywhere.
    prep_minutes: int | None = None

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
