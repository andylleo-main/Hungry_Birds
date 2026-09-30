import uuid
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.locations import label_for
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FulfilmentType(StrEnum):
    """How the customer gets the food.

    DINE_IN is the original behaviour - eat at, or collect from, the stall
    counter. DELIVERY sends it to a campus location and may involve a rider.
    """

    DINE_IN = "dine_in"
    DELIVERY = "delivery"


class OrderStatus(StrEnum):
    PLACED = "placed"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    READY = "ready"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status", values_callable=lambda e: [m.value for m in e]),
        default=OrderStatus.PLACED,
        nullable=False,
    )
    payment_method: Mapped[str] = mapped_column(String(20), default="cod", nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    fulfilment_type: Mapped[FulfilmentType] = mapped_column(
        Enum(
            FulfilmentType,
            name="fulfilment_type",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=FulfilmentType.DINE_IN,
        nullable=False,
    )
    # A code from app.core.locations, set only on a delivery order. The check
    # constraint below is what keeps the pair coherent; the router validates it
    # too, but a constraint means a future code path cannot quietly write a
    # delivery with nowhere to deliver it.
    delivery_location: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(fulfilment_type = 'delivery' AND delivery_location IS NOT NULL)"
            " OR (fulfilment_type = 'dine_in' AND delivery_location IS NULL)",
            name="ck_orders_delivery_location_matches_type",
        ),
    )

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    # Read-only link used to surface the customer's name/phone to the stall.
    # ALWAYS eager-load this before serialising an Order: OrderOut is built in
    # async paths (including the WebSocket broadcast) where a lazy load raises
    # MissingGreenlet. See _load_order_with_items in the orders router.
    customer: Mapped["User"] = relationship(lazy="raise")

    # Flattened onto the order so OrderOut picks them up by attribute name,
    # keeping every existing OrderOut.model_validate(order) call site unchanged.
    @property
    def customer_phone(self) -> str | None:
        return self.customer.phone

    @property
    def customer_name(self) -> str | None:
        return self.customer.full_name

    @property
    def delivery_location_label(self) -> str | None:
        """The human name of the drop-off point, for the vendor and the rider."""
        return label_for(self.delivery_location) if self.delivery_location else None


class OrderItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="SET NULL"), nullable=True
    )
    name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    price_snapshot: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    order: Mapped["Order"] = relationship(back_populates="items")
