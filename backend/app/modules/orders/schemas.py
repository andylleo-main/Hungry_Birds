import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.core.fields import MAX_ORDER_LINES, Note
from app.core.locations import MAX_LOCATION_CODE_LENGTH
from app.db.models.order import FulfilmentType, OrderStatus


class OrderItemIn(BaseModel):
    menu_item_id: uuid.UUID
    quantity: int = Field(ge=1, le=50)


class OrderCreate(BaseModel):
    vendor_id: uuid.UUID
    # Bounded at both ends: an empty order is meaningless, and every line costs
    # a database round trip when the order is priced, so a long list is a way
    # to turn one request into thousands of queries.
    items: list[OrderItemIn] = Field(min_length=1, max_length=MAX_ORDER_LINES)
    note: Note | None = None

    # Defaults to dine-in, which is what every order was before delivery
    # existed. That keeps a client which has not been updated yet working
    # instead of failing validation on a field it has never heard of.
    fulfilment_type: FulfilmentType = FulfilmentType.DINE_IN
    delivery_location: str | None = Field(default=None, max_length=MAX_LOCATION_CODE_LENGTH)

    @model_validator(mode="after")
    def location_must_match_fulfilment(self) -> "OrderCreate":
        """A delivery needs somewhere to go; a dine-in must not name one.

        Structure only - whether *this* stall delivers to *that* place is data,
        and lives in modules/fulfilment/service.py. Rejecting a stray location on
        a dine-in order matters because the field would otherwise be silently
        ignored, and a customer who picked a hostel and got "collect at the
        counter" would have no idea why.
        """
        if self.fulfilment_type is FulfilmentType.DELIVERY and not self.delivery_location:
            raise ValueError("delivery_location is required for a delivery order")
        if self.fulfilment_type is FulfilmentType.DINE_IN and self.delivery_location:
            raise ValueError("delivery_location must be omitted for a dine-in order")
        return self


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class OrderAssign(BaseModel):
    """Who is taking this delivery out.

    Exactly one of the two: a rider of this stall, or the merchant themselves.
    Passing neither un-assigns it, which is what a merchant needs when a rider
    calls in sick after being given the order.
    """

    rider_id: uuid.UUID | None = None
    self_delivery: bool = False

    @model_validator(mode="after")
    def only_one_courier(self) -> "OrderAssign":
        if self.rider_id is not None and self.self_delivery:
            raise ValueError("an order goes out with a rider or with you, not both")
        return self


class OrderItemOut(BaseModel):
    id: uuid.UUID
    menu_item_id: uuid.UUID | None
    name_snapshot: str
    price_snapshot: Decimal
    quantity: int

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: uuid.UUID
    vendor_id: uuid.UUID
    customer_id: uuid.UUID
    status: OrderStatus
    payment_method: str
    total_amount: Decimal
    note: str | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemOut]
    # Only ever reaches the order's own customer, the owning vendor, or an
    # admin - every route returning OrderOut is ownership-gated.
    customer_name: str | None
    customer_phone: str | None

    fulfilment_type: FulfilmentType
    delivery_location: str | None
    # Read off the model as a property, so the stall and the rider get a name
    # they can act on rather than a code they have to look up.
    delivery_location_label: str | None

    # Who is carrying it. rider_phone is what the customer's "call rider" button
    # dials, and it appears only once the merchant has assigned the order - so a
    # rider's number is never exposed to a customer they are not delivering to.
    rider_id: uuid.UUID | None
    rider_name: str | None
    rider_phone: str | None
    self_delivery: bool

    model_config = {"from_attributes": True}
