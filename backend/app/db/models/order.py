import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
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
    # "online" or "cod". Historical rows say "cashfree", from before the gateway
    # swap, which is why every reader asks whether this *is* "cod" rather than
    # whether it is online - the online value has had two spellings and may have
    # a third, while "cod" means one thing.
    payment_method: Mapped[str] = mapped_column(String(20), default="online", nullable=False)

    # How a pay-on-delivery order was settled at the door: "cash" or "upi".
    # Null on anything paid online, and on a cash order nobody has collected yet.
    # A stall counting its cash box at close wants exactly this column.
    collected_via: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # How long the kitchen says this one takes, in minutes.
    #
    # Snapshotted at placement from the dishes' own prep times, for the same
    # reason prices are snapshotted: a merchant editing a dish tomorrow must not
    # retroactively change what a customer was told today. Overwritten by
    # whatever the merchant types when they accept, which is the authoritative
    # number - they are looking at the actual kitchen.
    #
    # Prep only. The delivery buffer is not in here, so a merchant never has to
    # think about riders when answering "how long will this take to cook".
    prep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # When the customer is told to expect it, absolute.
    #
    # Stored rather than computed by each client, because "now" differs on every
    # phone and a countdown that disagrees between the web app and the stall is
    # worse than no countdown. Recomputed at placement and again on acceptance,
    # since the clock should start when the kitchen actually takes it on, not
    # when the order was paid for.
    ready_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The Razorpay QR a rider is currently showing for this order, if any.
    # Indexed, because the qr_code.credited webhook names only the QR and this is
    # the entire mapping back to an order.
    cod_qr_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)

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

    # Promotional credit taken off this order. Never negative, and never more
    # than 60% of the total, because that is the redemption cap.
    #
    # **total_amount is not reduced by this**, and that is deliberate. It is
    # documented above as the order's value, it is snapshotted at placement, nine
    # analytics queries sum it, and the Razorpay webhook compares against it.
    # Redefining it as "what the customer pays" would change what every one of
    # those figures means without a single call site changing - and would
    # under-report what the stall is owed, since Hungry Birds funds the discount
    # rather than the stall. So the gross stays here and `amount_due` below is
    # the single name for what anybody is actually charged or collects.
    cashback_applied: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )

    # A discount code applied to this order. Zero on almost every order, and
    # never non-zero at the same time as cashback_applied - the two promotions do
    # not stack, which OrderCreate refuses structurally.
    #
    # Same treatment as cashback: total_amount is not reduced by it, because
    # Hungry Birds funds the discount rather than the stall.
    coupon_discount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )

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
    def amount_due(self) -> Decimal:
        """What the customer actually has to hand over.

        The only figure any money path should read: the gateway amount, the
        webhook's amount check, a rider's collection QR, the "Collect Rs.X"
        guard, and the COLLECT line on a printed ticket. `grep amount_due` is
        meant to find all of them.

        Not what the stall earned - that is `total_amount`, which this never
        reduces. The difference is what Hungry Birds is funding.

        Cannot reach zero. Cashback is capped at 60% of the cart, and a coupon is
        capped on its way in so that at least one rupee is left payable - so
        there is never a zero-rupee gateway order to special-case.
        """
        return (
            Decimal(self.total_amount)
            - Decimal(self.cashback_applied)
            - Decimal(self.coupon_discount)
        )

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
    # SET NULL on both, matching menu_item_id above and for the same reason: a
    # merchant tidying their menu must not take order history with them.
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_item_variants.id", ondelete="SET NULL"), nullable=True
    )
    name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    # Kept in its own column rather than folded into name_snapshot. Concatenating
    # would destroy grouping - the stall's analytics want "Butter Paneer" across
    # every size *and* the split between them - and both apps already render the
    # dish name on a line of its own.
    variant_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
