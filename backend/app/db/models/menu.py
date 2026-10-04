import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MenuCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "menu_categories"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    vendor: Mapped["Vendor"] = relationship(back_populates="categories")
    # NOT delete-orphan. The foreign key below says ondelete="SET NULL",
    # meaning a deleted section leaves its dishes on the menu and merely
    # uncategorises them - which is what a vendor reorganising their menu
    # expects. A delete-orphan cascade here overrode that and had SQLAlchemy
    # delete the items itself, so removing a section quietly destroyed
    # everything in it. passive_deletes lets the database apply the SET NULL
    # it was always configured for.
    items: Mapped[list["MenuItem"]] = relationship(
        back_populates="category", passive_deletes=True
    )


class MenuItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "menu_items"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_categories.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    vendor: Mapped["Vendor"] = relationship(back_populates="items")
    category: Mapped["MenuCategory | None"] = relationship(back_populates="items")

    # The price the merchant has asked to change to, waiting on an admin.
    #
    # Deliberately a second column rather than a flag on `price`, and that is the
    # whole of the enforcement: the live price keeps selling, and nothing in any
    # pricing path can see this one. There is no "WHERE pending_price IS NULL"
    # filter anywhere and there must not be - an item with a change pending is
    # fully on sale at its old price, which is the product decision.
    #
    # Never appears on an input schema. A merchant writes it only through
    # PUT /vendors/me/items/{id}/price, which decides what to do with the number
    # rather than storing what it was given.
    pending_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    pending_price_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Eagerly loaded, which is a deliberate break from the lazy="raise" used on
    # Order.customer and Order.rider. That pattern is right where a relationship
    # is only sometimes wanted and a missing loader should fail loudly. Variants
    # are serialised on every item read, including the public menu, so "always"
    # is the honest answer - and lazy="raise" would mean every existing call site
    # raises MissingGreenlet in async until it is taught to load them.
    variants: Mapped[list["MenuItemVariant"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="MenuItemVariant.sort_order",
        lazy="selectin",
    )

    @property
    def price_awaiting_approval(self) -> bool:
        """So the merchant app can draw a badge without reasoning about nulls."""
        return self.pending_price is not None


class MenuItemVariant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One size of a dish: "Half" at 120, "Full" at 200.

    An item with no rows here is priced by MenuItem.price and behaves exactly as
    it did before variants existed - which is why nothing had to be backfilled
    and why the storefront kept working during the migration. resolve_line_price
    is the only code that knows about the two shapes.

    CASCADE from the item rather than SET NULL, unlike menu_items.category_id: a
    size has no meaning without its dish, whereas a dish outlives its section.
    """

    __tablename__ = "menu_item_variants"

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    # Gated identically to the item's own price, and that is load-bearing rather
    # than tidy: without it a merchant with a frozen item price adds a variant
    # called "Regular" at the number they wanted and sells at it immediately.
    pending_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    pending_price_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Per variant, because "Full is finished, Half is still on" is the ordinary
    # case and the item-level flag cannot say it.
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    item: Mapped["MenuItem"] = relationship(back_populates="variants")

    __table_args__ = (
        # Two variants called "Full" on one dish leaves nobody able to say which
        # one an order meant.
        Index(
            "uq_menu_item_variants_item_name",
            "item_id",
            text("lower(name)"),
            unique=True,
        ),
    )

    @property
    def price_awaiting_approval(self) -> bool:
        return self.pending_price is not None


class PriceChangeKind(StrEnum):
    """What happened to a price. Stored as VARCHAR, like PaymentStatus.

    Not a native Postgres enum, for the reason payment.py gives: adding a value
    should be a code change, not an ALTER TYPE that cannot be rolled back.
    """

    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    # A price set at creation, which is not gated. Recorded anyway - see below.
    CREATED = "created"


class MenuPriceChange(UUIDPrimaryKeyMixin, Base):
    """Append-only history of every price this platform has carried.

    The admin queue reads the pending rows out of menu_items directly, so this
    table is not needed to make approvals work. It exists for the hole that
    cannot be closed: adding a dish is deliberately not gated, so a merchant who
    wants a price an admin refused can add a new dish at that price and delete
    the old one. Gating creation is the only prevention and it was explicitly
    ruled out - a new size would be unsellable until somebody woke up.

    So CREATED rows are recorded alongside the rest, and the queue can answer
    "this stall replaced six dishes this week". Detection rather than
    prevention, and the comment is here so nobody later mistakes the gate for
    airtight.

    name_snapshot survives the item being deleted, same as OrderItem's.
    """

    __tablename__ = "menu_price_changes"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="SET NULL"), nullable=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_item_variants.id", ondelete="SET NULL"),
        nullable=True,
    )
    name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    # Null when the row records a dish being created rather than repriced.
    old_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    new_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    kind: Mapped[PriceChangeKind] = mapped_column(String(16), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_menu_price_changes_vendor", "vendor_id", "created_at"),
    )
