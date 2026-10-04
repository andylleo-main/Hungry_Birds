import uuid
from datetime import date
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.locations import label_for
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.models.payment import PaymentStatus, PaymentStatusType


class FulfilmentType(StrEnum):
    """How the customer gets the food.

    DINE_IN is the original behaviour - eat at, or collect from, the stall
    counter. DELIVERY sends it to a campus location and may involve a rider.
    """

    DINE_IN = "dine_in"
    DELIVERY = "delivery"


class OrderStatus(StrEnum):
    # Created, but not yet paid for, so no stall has seen it. Orders begin here
    # now that payment happens before a stall is asked to cook.
    AWAITING_PAYMENT = "awaiting_payment"
    PLACED = "placed"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    READY = "ready"
    # Only reachable on a delivery: the food has left the stall with a rider, or
    # with the merchant themselves. A dine-in order goes from READY straight to
    # COMPLETED when it is handed across the counter.
    OUT_FOR_DELIVERY = "out_for_delivery"
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
        default=OrderStatus.AWAITING_PAYMENT,
        nullable=False,
    )
    payment_method: Mapped[str] = mapped_column(String(20), default="cashfree", nullable=False)

    # What a customer quotes when something goes wrong, and what gets printed on
    # the stall's ticket. Format NNNNNN-RRRR, e.g. "014237-5096".
    #
    # Digits only, deliberately. This gets read aloud across a counter and over a
    # phone, where letters need a "B as in Bombay" protocol, and it gets typed
    # into a numeric keypad on the admin support screen. A "HB-" prefix would
    # carry no information - every order here is a Hungry Birds order - and cost
    # two syllables on every support call; the receipt template says the name.
    #
    # The six-digit half comes from the order_number_seq sequence and is what
    # makes the string unique; the four random digits only stop the series being
    # walkable. Because uniqueness is structural rather than probabilistic there
    # is no retry loop anywhere, and the unique index can never actually fire.
    #
    # nextval() is not transactional, so an order that fails validation after the
    # number is drawn burns it. The series has gaps on purpose. Do not "fix" them
    # with a renumbering migration: these numbers are on printed receipts and in
    # refund references.
    #
    # NEVER make this a lookup key on a route a customer can reach. The UUID is
    # the identifier; this is a display and support field. Four random digits is
    # thin cover against guessing, and it is only sufficient because nothing
    # accepts this as input outside an admin-gated route.
    order_number: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)

    # The small number a stall calls out: 1, 2, 3 and up, per stall, per day.
    #
    # Allocated when the order enters the stall's queue - not when the row is
    # created. An abandoned checkout must not burn a token, or the stall calls
    # "number 12!" when 9, 10 and 11 never existed. See allocate_token.
    #
    # Null on every order placed before this column existed, and on anything
    # still awaiting payment. Inventing tokens for historical orders would print
    # a number on a reprint that nobody ever heard called.
    token_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # The service day the token belongs to, on the Asia/Kolkata calendar.
    #
    # Stored rather than computed from created_at so it can carry a unique index,
    # and so that changing the day-boundary policy later cannot silently
    # renumber orders that have already been served. UTC would be wrong: UTC
    # midnight is 05:30 IST, so tokens would restart at 1 mid-breakfast while
    # number 87 was still waiting.
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # The money state, and the only copy of it. See db/models/payment.py.
    #
    # Typed through PaymentStatusType rather than a bare String so a read gives
    # back a PaymentStatus. With a plain String it comes back as `str`, and every
    # `payment_status is PaymentStatus.PAID` in the codebase is then silently
    # False forever - which is exactly what happened, and what the refund tests
    # caught.
    payment_status: Mapped[PaymentStatus] = mapped_column(
        PaymentStatusType, default=PaymentStatus.PENDING, nullable=False
    )
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

    # Who is carrying it. Either a rider of this stall, or the merchant
    # themselves, or nobody yet - never both, which the constraint below makes
    # true at the database rather than only in the handler that sets them.
    #
    # SET NULL rather than CASCADE: a rider leaving must not take the history of
    # every order they delivered with them.
    rider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.id", ondelete="SET NULL"), nullable=True
    )
    self_delivery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # The four digits a customer reads out when their food arrives, and the
    # rider types in to close the order. Proof that a handover actually
    # happened, rather than a rider tapping "delivered" from the stall.
    #
    # Set on delivery orders only, and stored in the clear on purpose: it is not
    # a credential for reaching anything, the customer sees it anyway, and the
    # stall needs to be able to read it back to somebody whose phone has died.
    # Four digits rather than six because it gets said aloud at a hostel gate -
    # guessing is bounded by the attempt limit, not by length.
    delivery_code: Mapped[str | None] = mapped_column(String(8), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(fulfilment_type = 'delivery' AND delivery_location IS NOT NULL)"
            " OR (fulfilment_type = 'dine_in' AND delivery_location IS NULL)",
            name="ck_orders_delivery_location_matches_type",
        ),
        CheckConstraint(
            "NOT (rider_id IS NOT NULL AND self_delivery)",
            name="ck_orders_one_courier",
        ),
        # Belt and braces over allocate_token, which is already race-free. If a
        # future code path allocates some other way, this makes it fail loudly
        # rather than print two number 7s for the same stall on the same day.
        # Partial, because every historical order and every unpaid one is NULL.
        Index(
            "uq_orders_vendor_day_token",
            "vendor_id",
            "service_date",
            "token_number",
            unique=True,
            postgresql_where=text("token_number IS NOT NULL"),
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

    # lazy="raise" for the same reason as customer above: rider_name and
    # rider_phone are read through this during serialisation, which happens in
    # async paths including the WebSocket broadcast, where a lazy load does not
    # merely go slow - it raises MissingGreenlet. Failing loudly on a missing
    # selectinload beats discovering it in production.
    rider: Mapped["Rider | None"] = relationship(lazy="raise")

    # Flattened onto the order so OrderOut picks them up by attribute name,
    # keeping every existing OrderOut.model_validate(order) call site unchanged.
    @property
    def customer_phone(self) -> str | None:
        return self.customer.phone

    @property
    def customer_name(self) -> str | None:
        return self.customer.full_name

    @property
    def rider_name(self) -> str | None:
        return self.rider.display_name if self.rider else None

    @property
    def rider_phone(self) -> str | None:
        """The number the customer's "call rider" button dials.

        Only ever reaches the order's own customer, the owning vendor, or an
        admin - every route returning an OrderOut is ownership-gated - and only
        once the merchant has assigned this order to this rider.
        """
        return self.rider.phone if self.rider else None

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


class VendorTokenCounter(Base):
    """The last token number handed out by one stall on one service day.

    Exists so allocate_token can be a single atomic statement. The obvious
    alternative - SELECT max(token_number) + 1 - is wrong under concurrency: at
    READ COMMITTED two orders placed in the same instant both read 7 and both
    write 8, and a lunch rush is exactly when that happens.

    INSERT ... ON CONFLICT DO UPDATE ... RETURNING on this table is atomic by
    construction, needs no retry loop, and leaves a row an admin can read to
    answer "what number is this stall on?". A unique-constraint-and-retry scheme
    would also be correct but would re-run the whole order insert on collision,
    and rollback expires the session's objects - the hazard riders/router.py
    already documents at length for a single-row insert.

    One row per stall per day, so roughly 11k rows a year at thirty stalls.
    That is not worth a cleanup job; it is worth keeping, because it is the only
    record of what a stall's numbering actually did on a given day.
    """

    __tablename__ = "vendor_token_counters"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        primary_key=True,
    )
    service_date: Mapped[date] = mapped_column(Date, primary_key=True)
    last_token: Mapped[int] = mapped_column(Integer, nullable=False)
