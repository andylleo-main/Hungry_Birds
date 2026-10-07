"""Discount codes, and the record of who spent one on what.

A coupon is simple; a *use* of one is not. The hard part is that a code with one
use left must not be taken twice, and that an order the stall then refuses has to
give the use back - otherwise the one student who got there first has burnt it on
food they never received.

So a use has three states rather than being a counter that goes up. It is **held**
when the order is placed, **consumed** when the order completes, and **returned**
when the stall refuses it or an admin hands it back. That is deliberately the same
shape `cashback_entries` already has, for the same reasons; two promotions behaving
differently under a refusal would be two things to remember instead of one.

The number of uses is **derived** from these rows, never stored. A stored counter
drifts from the rows behind it and then needs a repair button; a count of rows
cannot.

Where a code works is `all_stalls` plus a set of rows in `coupon_vendors`. It
began as a single nullable column, which could say "this stall" or "all of them"
but not "these three".

The flag is not redundant with "the set is empty", and that is the whole reason
it exists - see `all_stalls` below.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _enum(cls, length: int):
    """A StrEnum stored as VARCHAR, the way payments.status is.

    Not a Postgres enum: adding a value later should be a code change rather
    than an ALTER TYPE the same transaction then cannot use. `values_callable`
    matters - without it SQLAlchemy persists the member *name*, writing "PERCENT"
    and reading back something that matches nothing.
    """
    return Enum(
        cls,
        native_enum=False,
        create_constraint=False,
        length=length,
        values_callable=lambda e: [m.value for m in e],
    )


class DiscountType(StrEnum):
    PERCENT = "percent"
    FLAT = "flat"


class ExpiryType(StrEnum):
    """What ends a coupon: running out of uses, or running out of time."""

    COUNT = "count"
    DATE = "date"


class CouponAudience(StrEnum):
    """Who may use a code.

    ANYONE is the ordinary case - type it and it works. The other three narrow it:

      * FIRST_ORDER is a welcome code, spent by somebody who has never completed
        an order here.
      * NAMED is for a listed set of addresses, which is how an apology gets made
        to the people it is owed to rather than to everybody who hears about it.
      * AUTOMATIC has no code to type at all: it applies itself at checkout to
        anybody eligible. The loudest of the four, and the one to be careful with.
    """

    ANYONE = "anyone"
    FIRST_ORDER = "first_order"
    NAMED = "named"
    AUTOMATIC = "automatic"


class RedemptionState(StrEnum):
    """Where one use of a coupon has got to.

    HELD is a use reserved by an order that has not finished. It counts against
    the coupon's limit immediately - that is the whole point, so a one-use code
    cannot be taken by two checkouts at once - but nothing has been earned yet.

    CONSUMED is a use that stuck: the order completed.

    RETURNED is a use given back, because the stall refused the order or an admin
    handed it back. It stays as a row rather than being deleted, so the history
    of a code is readable, and it is excluded from every count.
    """

    HELD = "held"
    CONSUMED = "consumed"
    RETURNED = "returned"


class Coupon(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "coupons"

    # Stored upper-cased, and compared upper-cased. A code is read off a poster
    # and typed by a hungry person; "welcome100" has to be the same code.
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    discount_type: Mapped[DiscountType] = mapped_column(_enum(DiscountType, 16), nullable=False)
    # A percentage when the type is PERCENT, rupees when it is FLAT.
    discount_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # The ceiling on a percentage. Meaningless on a flat coupon - 20% capped at
    # ₹50 is a sentence; ₹100 capped at ₹50 is a contradiction - so it is ignored
    # there rather than being a second way to say the same thing.
    max_discount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    expiry_type: Mapped[ExpiryType] = mapped_column(_enum(ExpiryType, 16), nullable=False)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The cart has to be worth at least this before the code applies. Measured on
    # the gross, like the stall's delivery minimum: it is about the size of the
    # order, not about who paid for it.
    min_order_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), default=Decimal("0.00"), nullable=False
    )

    audience: Mapped[CouponAudience] = mapped_column(
        _enum(CouponAudience, 16), default=CouponAudience.ANYONE, nullable=False
    )

    # Whether this code works at every stall on campus, or only at the ones in
    # `coupon_vendors`.
    #
    # **Deliberately a flag rather than "the set is empty"**, which is what it
    # looked like it could be. Two reasons, and both are about failing in the
    # safe direction:
    #
    #   * A stall can be deleted - `remove_demo_stalls.py` does exactly that -
    #     and CASCADE takes its pinning rows with it. Without the flag, a coupon
    #     pinned only to a removed stall would have an empty set, and an empty
    #     set meaning "everywhere" would turn it loose on the whole campus. With
    #     the flag it works nowhere instead, which is the direction a money bug
    #     should fail in. The nullable `vendor_id` this replaced had the same
    #     protection by accident: CASCADE deleted the coupon outright.
    #   * An admin who unticks the last stall has not said "every stall". Nothing
    #     could tell that apart from "I meant to pick some and did not", so the
    #     form asks for the choice and the row records the answer.
    all_stalls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Off without deleting. An exhausted or withdrawn code keeps its redemption
    # history, which is the point of not deleting it.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # One student, one use - enforced by the partial index on the redemptions
    # table below, not only by the handler that checks it.
    one_per_customer: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Whether it shows on a student's offers page. Off by default: a code handed
    # out on a poster is not meant to be discoverable by everybody who did not
    # see the poster.
    show_in_offers: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    redemptions: Mapped[list["CouponRedemption"]] = relationship(
        back_populates="coupon", cascade="all, delete-orphan", lazy="raise"
    )
    audience_members: Mapped[list["CouponAudienceMember"]] = relationship(
        back_populates="coupon", cascade="all, delete-orphan", lazy="raise"
    )
    stalls: Mapped[list["CouponVendor"]] = relationship(
        back_populates="coupon", cascade="all, delete-orphan", lazy="raise"
    )


class CouponVendor(Base):
    """One stall a code is pinned to. Read only when `Coupon.all_stalls` is off.

    A row per stall rather than a column of them, for the reason
    `coupon_audience_members` gives: one stall can be added or removed without
    rewriting the set, and "does this code work here?" is an indexed lookup
    rather than a scan.

    CASCADE on both sides: a deleted coupon takes its pinning, and a deleted
    stall takes its own. A coupon left pinned to nothing then works nowhere
    rather than everywhere - see `Coupon.all_stalls` for why that matters.
    """

    __tablename__ = "coupon_vendors"

    coupon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coupons.id", ondelete="CASCADE"), primary_key=True
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), primary_key=True
    )

    coupon: Mapped["Coupon"] = relationship(back_populates="stalls")

    __table_args__ = (
        # "Which codes work at this stall", for the delete-cascade and for any
        # future question asked from the stall's side. The composite primary key
        # already indexes the other direction.
        Index("ix_coupon_vendors_vendor", "vendor_id"),
    )


class CouponAudienceMember(Base):
    """One address allowed to use a NAMED coupon.

    A row per address rather than a column holding a list, so one person can be
    added or removed without rewriting the set - and so the same question
    ("may this address use this code?") is an indexed lookup rather than a scan
    of a string.
    """

    __tablename__ = "coupon_audience_members"

    coupon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coupons.id", ondelete="CASCADE"), primary_key=True
    )
    # The address as typed, lower-cased. Deliberately not a user_id: an admin
    # hands a code to somebody who may not have signed in yet, and requiring the
    # account to exist first would make that impossible.
    email: Mapped[str] = mapped_column(String(320), primary_key=True)

    coupon: Mapped["Coupon"] = relationship(back_populates="audience_members")


class CouponRedemption(UUIDPrimaryKeyMixin, Base):
    """One use of one coupon, in one of three states."""

    __tablename__ = "coupon_redemptions"

    coupon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("coupons.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL, matching cashback_entries and order_items: deleting an order must
    # not delete the record that somebody used a code.
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )

    # What it was actually worth on that cart, after the cap and the floor. Kept
    # rather than recomputed, because the coupon can be edited afterwards and
    # what a student was given does not change when it is.
    discount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    state: Mapped[RedemptionState] = mapped_column(
        _enum(RedemptionState, 16), default=RedemptionState.HELD, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # When it stopped being held - consumed or returned. Null while it is still
    # out with an order nobody has finished.
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    coupon: Mapped["Coupon"] = relationship(back_populates="redemptions")

    __table_args__ = (
        # One coupon per order. An order cannot carry two codes, and this is
        # where that is true rather than in the handler that assumes it. Nulls
        # do not collide in Postgres, so orders deleted out from under their
        # redemptions do not start conflicting with each other.
        UniqueConstraint("order_id", name="uq_coupon_one_per_order"),
        # Every question asked of this table is "what has happened to this
        # coupon", filtered by state.
        Index("ix_coupon_redemptions_coupon", "coupon_id", "state"),
        Index("ix_coupon_redemptions_user", "user_id"),
    )

    # **No unique index on (coupon_id, user_id).** It is the obvious one to want
    # - "one use per customer" is a flag on the coupon - and it would be wrong.
    # A partial unique index can only read this table, so it could not know
    # whether the coupon it belongs to has that flag set, and a coupon that
    # deliberately allows repeat use would have its second use rejected by the
    # database with nothing in the handler to explain why.
    #
    # Denormalising the flag onto each row would make the index possible, at the
    # cost of rows disagreeing with their coupon the moment an admin toggles it.
    #
    # So the enforcement is the lock instead: hold() takes `SELECT … FOR UPDATE`
    # on the coupon row before it counts anything, which serialises every use of
    # one code. That is the same thing the count limit needs anyway, so the
    # per-customer check rides on a guarantee that already had to exist.
