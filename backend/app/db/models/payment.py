import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PaymentStatus(StrEnum):
    """Where the money is.

    Deliberately a separate axis from OrderStatus, which is where the *food* is.
    The two are genuinely independent: an order can be paid and being cooked,
    paid and rejected, paid and refunded. Folding refunds into the fulfilment
    enum would need a value for every combination, and would lose the one
    distinction that matters when something has gone wrong - whether a refund was
    issued or merely attempted.
    """

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    # Nobody completed the payment in time. Swept locally, after the gateway's
    # own payment window has already closed.
    EXPIRED = "expired"
    # Pay on delivery: the food is being made and the money is owed at the door.
    #
    # Distinct from PENDING, and the distinction is what keeps cash orders alive.
    # PENDING means a checkout nobody finished, which sweep_abandoned cancels
    # after twenty minutes; a cash order would be killed mid-cook by that sweep
    # if it shared the state. DUE says the opposite - this one is expected to go
    # on, and settles at the door.
    DUE = "due"
    # Pay on delivery that ended without the money ever being taken: refused at
    # the door, nobody home, cancelled before the rider arrived. Nothing is owed
    # in either direction, which is what distinguishes it from FAILED (a payment
    # that was attempted and did not work) and from REFUNDED (money that moved
    # twice).
    WAIVED = "waived"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"
    # The refund call did not succeed. Holds real money, so it is a state
    # somebody has to see rather than a retry that disappears.
    REFUND_FAILED = "refund_failed"


# Stored as VARCHAR rather than a Postgres enum, and without a CHECK
# constraint, so adding a state later is a code change instead of an ALTER TYPE
# that cannot be reversed and that Postgres refuses to let the same transaction
# use. `values_callable` matters: SQLAlchemy otherwise persists a member's
# *name*, so this would write "PAID" and read back something that matches
# nothing.
PaymentStatusType = Enum(
    PaymentStatus,
    native_enum=False,
    create_constraint=False,
    length=20,
    values_callable=lambda e: [m.value for m in e],
)


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The money side of one order.

    One row per order, holding one gateway order that is created once and reused.
    Razorpay allows several payment attempts against a single order, so retries
    happen at the gateway rather than by us minting a new one - which is what
    makes paying twice structurally impossible instead of merely unlikely.
    """

    __tablename__ = "payments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # The gateway's id for this order. **Razorpay mints it**, unlike Cashfree
    # where we chose "hb_{order_id}" and could parse the order back out of it, so
    # this is the lookup key every inbound webhook is matched on - hence unique
    # and indexed rather than merely stored.
    gateway_order_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    gateway_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Snapshot of what we told the gateway to collect. The webhook compares
    # against this, so a payload claiming a different figure cannot mark an order
    # paid.
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)

    # Note there is no status column here. The money state lives on
    # orders.payment_status and only there, because two copies of the same fact
    # are two chances to disagree - and the one that matters is read on every
    # order serialisation and every vendor queue fetch. This table holds what
    # the gateway knows: its ids, what we asked it to collect, and the refund
    # bookkeeping.

    # There is no payment_session_id any more. Cashfree handed the browser an
    # opaque session; Razorpay Checkout takes the gateway order id and the
    # publishable key, both of which are already known without storing anything.

    # Razorpay's id for the refund, recorded once it exists. Note it is written
    # *after* the fact rather than chosen in advance: Cashfree accepted an id of
    # ours and was idempotent on it, which is the guarantee attempt_refund now
    # has to reconstruct by listing existing refunds before creating one.
    refund_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    refund_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    order: Mapped["Order"] = relationship(lazy="raise")


class PaymentEvent(UUIDPrimaryKeyMixin, Base):
    """Every webhook Cashfree has sent us, and what we did about it.

    This is the idempotency guard, and it is a table rather than a Redis key on
    purpose: the row is written in the same transaction as the state change it
    authorises, so a rollback releases the guard too. A Redis SETNX would be
    taken before the work and kept after a failed commit, which silently swallows
    Cashfree's retry and leaves money unbooked with no trace.

    It doubles as the audit trail for the day somebody disputes a refund.
    """

    __tablename__ = "payment_events"

    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
    )

    # Cashfree's own event id when the payload carries one, otherwise a digest of
    # the signed timestamp and body - stable across retries because Cashfree
    # replays both unchanged.
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # applied | duplicate | rejected_transition | amount_mismatch | unknown_order
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
