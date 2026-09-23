import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.db.models.order import OrderStatus


class OrderItemIn(BaseModel):
    menu_item_id: uuid.UUID
    quantity: int = Field(ge=1, le=50)


class OrderCreate(BaseModel):
    vendor_id: uuid.UUID
    items: list[OrderItemIn] = Field(min_length=1)
    note: str | None = None


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


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

    model_config = {"from_attributes": True}
