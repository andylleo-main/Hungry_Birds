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
    # Nobody completed the payment in time. Swept locally, after Cashfree's own
    # order expiry has already closed the window.
    EXPIRED = "expired"
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

    One row per order, holding one Cashfree order that is created once and
    reused. Cashfree allows several payment attempts against a single order, so
    retries happen at the gateway rather than by us minting a new one - which is
    what makes paying twice structurally impossible instead of merely unlikely.
    """

    __tablename__ = "payments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # Our own id for the Cashfree order, derived from the order id so it can be
    # recomputed rather than looked up.
    cf_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    cf_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Snapshot of what we told Cashfree to collect. The webhook compares against
    # this, so a payload claiming a different figure cannot mark an order paid.
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)

    # Note there is no status column here. The money state lives on
    # orders.payment_status and only there, because two copies of the same fact
    # are two chances to disagree - and the one that matters is read on every
    # order serialisation and every vendor queue fetch. This table holds what
    # the gateway knows: its ids, what we asked it to collect, and the refund
    # bookkeeping.

    # What the browser SDK needs to open the checkout. Transient - Cashfree
    # expires it - but kept so a customer who closed the sheet can be handed the
    # same session again rather than a second order.
    payment_session_id: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Generated once and reused across attempts. Cashfree's refund API is
    # idempotent on this, so retrying can never refund twice; a fresh id per
    # attempt is exactly the bug that would.
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
