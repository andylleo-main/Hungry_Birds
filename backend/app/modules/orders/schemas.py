import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.core.fields import MAX_ORDER_LINES, Note
from app.core.locations import MAX_LOCATION_CODE_LENGTH
from app.db.models.order import FulfilmentType, OrderStatus
from app.db.models.payment import PaymentStatus


class OrderItemIn(BaseModel):
    menu_item_id: uuid.UUID
    # Required when the dish has sizes, refused when it does not - decided by
    # resolve_line_price rather than here, since only the stall's menu knows
    # which it is. Optional with a default so a client ordering a dish without
    # sizes is unchanged, the same reasoning fulfilment_type is defaulted below.
    variant_id: uuid.UUID | None = None
    quantity: int = Field(ge=1, le=50)


class PaymentMethod(StrEnum):
    """How an order will be paid for.

    "online" rather than the gateway's name, deliberately. The column has already
    held "cashfree" and now holds "razorpay" for historical rows, and clients
    branch on this value - so the only question anything asks is whether it *is*
    cod, never whether it is some particular gateway.
    """

    ONLINE = "online"
    COD = "cod"


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

    # Defaults to online for the same reason fulfilment defaults to dine-in: an
    # older client that has never heard of this field keeps working, and the
    # default is the conservative one - money up front.
    payment_method: PaymentMethod = PaymentMethod.ONLINE

    @model_validator(mode="after")
    def cash_is_for_deliveries(self) -> "OrderCreate":
        """Pay on delivery means a rider collecting at a door.

        There is nobody to collect from a dine-in customer: they are standing at
        the counter, where the stall would have to handle the money and mark it
        collected itself. That is a different feature, and refusing here is
        better than silently charging them online instead.

        Whether cash is allowed at all is a deployment setting, checked in the
        route - this is only about the shape being coherent.
        """
        if self.payment_method is PaymentMethod.COD and self.fulfilment_type is not FulfilmentType.DELIVERY:
            raise ValueError("Pay on delivery is only available for delivery orders")
        return self

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


class RiderStatusUpdate(OrderStatusUpdate):
    """What a rider sends when moving an order along.

    `delivery_code` is required to complete a delivery and ignored otherwise - a
    rider marking an order picked up has nothing to prove yet.
    """

    delivery_code: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8)
    ] | None = None


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
    # "Half", "Full", or null for a dish that has no sizes. Separate from the
    # name rather than appended to it, so a stall's analytics can group by dish
    # and still break down by size.
    variant_name_snapshot: str | None = None
    price_snapshot: Decimal
    quantity: int

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: uuid.UUID
    # What a customer quotes to support and what prints on the stall's ticket.
    # The id above stays the identifier; this is for people to say out loud.
    order_number: str
    # The small number the stall calls across the counter. Null until the order
    # reaches the queue, and on every order placed before tokens existed.
    token_number: int | None
    vendor_id: uuid.UUID
    customer_id: uuid.UUID
    status: OrderStatus
    payment_method: str
    payment_status: PaymentStatus
    # "cash" or "upi" once a rider has collected at the door; null on anything
    # paid online, and on a cash order nobody has collected yet. A stall
    # counting its till at close wants exactly this.
    collected_via: str | None = None
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


class OrderWithCodeOut(OrderOut):
    """An order, plus the handover code - for everybody except the rider.

    The split is the whole point of the code. A rider who could read it could
    close an order without ever reaching the customer, which is exactly what it
    exists to prevent. So the base OrderOut above carries no code and is what the
    rider endpoints return; this subclass is what the customer, the stall and the
    admin get.

    Safe for the WebSocket broadcast too: the order and vendor channels reach the
    customer, the owning stall and an admin, and riders have no channel - they
    poll the rider endpoints, which return the base model.
    """

    delivery_code: str | None
