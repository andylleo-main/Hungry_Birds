"""Promotional cashback, as a ledger rather than a balance.

A balance column cannot survive these rules. A credit is a percentage of an
order *capped* at a figure, it expires a fixed number of days after it is
earned, it can only be spent at the kind of stall it came from, and a stall
refusing an order has to give a redemption back. Any one of those is awkward
against a single number; together they make the number unexplainable.

So every movement is a row, nothing is ever updated, and the balance is derived.
That also means any rupee a student has can be accounted for - which matters
because this is the first thing in the project that creates money rather than
moving money somebody already owed.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class CashbackKind(StrEnum):
    """Which wallet. The two never mix, on the user's instruction.

    A balance earned at an ordinary stall is unspendable at Gourmet Kitchen and
    the reverse, which also means "one wallet per order" needs no rule of its
    own: an order has exactly one stall, so it has exactly one kind.
    """

    NORMAL = "normal"
    GOURMET = "gourmet"


# VARCHAR rather than a Postgres enum, for the reason payment.py's
# PaymentStatusType spells out: adding a kind later should be a code change, not
# an ALTER TYPE that the same transaction then cannot use. values_callable
# matters - without it SQLAlchemy persists the member *name*, writing "NORMAL"
# and reading back something that matches nothing.
CashbackKindType = Enum(
    CashbackKind,
    native_enum=False,
    create_constraint=False,
    length=16,
    values_callable=lambda e: [m.value for m in e],
)


class CashbackReason(StrEnum):
    """Why this row exists.

    Three, and each is load-bearing somewhere:

      * EARNED is the only one that mints. Idempotent per order.
      * REDEEMED is the only negative one.
      * RETURNED gives a redemption back when the stall refuses the order. Not
        the same as EARNED - it returns a student's own money rather than
        creating any - and keeping them apart is what stops a refused order from
        counting as a completed one in anybody's figures.
    """

    EARNED = "earned"
    REDEEMED = "redeemed"
    RETURNED = "returned"


CashbackReasonType = Enum(
    CashbackReason,
    native_enum=False,
    create_constraint=False,
    length=16,
    values_callable=lambda e: [m.value for m in e],
)


class CashbackEntry(UUIDPrimaryKeyMixin, Base):
    """One movement of promotional credit. Append-only.

    Nothing updates a row here, ever. A redemption that has to be undone is
    another row, which is why `reason` distinguishes RETURNED from EARNED.
    """

    __tablename__ = "cashback_entries"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    kind: Mapped[CashbackKind] = mapped_column(CashbackKindType, nullable=False)

    # Signed: a credit is positive, a redemption negative. One column rather
    # than two, so the ledger reads in one direction and a balance is a walk
    # rather than a subtraction between two sums.
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    reason: Mapped[CashbackReason] = mapped_column(CashbackReasonType, nullable=False)

    # Which order earned or spent it. SET NULL rather than CASCADE, matching
    # order_items.menu_item_id: deleting an order must not delete the record of
    # money a student is holding.
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )

    # Credits only; null on a redemption or a return, which have nothing to
    # expire. Frozen here at the moment of earning from CASHBACK_EXPIRY_DAYS, so
    # changing that setting later cannot retroactively kill or revive a balance
    # somebody was already shown a date for.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set explicitly rather than through TimestampMixin: the balance walk orders
    # by this, so it is part of the data rather than bookkeeping, and an
    # append-only table has no use for the mixin's updated_at.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        # The whole of the idempotence story, enforced where it cannot be raced.
        #
        # Earning happens on COMPLETED, which both the stall's route and the
        # rider's can reach, and a double-tap or a retried request would
        # otherwise credit twice. Returning happens when a stall refuses, and
        # the refusal path can be re-entered. Checking in Python first gives the
        # good error message; this is what makes it true.
        #
        # Partial, because REDEEMED is excluded: one order has exactly one
        # redemption today, but nothing in the scheme says it must, and a
        # constraint is the wrong place to decide that.
        Index(
            "uq_cashback_once_per_order_reason",
            "order_id",
            "reason",
            unique=True,
            postgresql_where=text("order_id IS NOT NULL AND reason IN ('earned', 'returned')"),
        ),
        # The balance walk always asks for one user's rows in order. Without
        # this it is a sequential scan of everybody's ledger on every checkout.
        Index("ix_cashback_user_created", "user_id", "created_at"),
    )
