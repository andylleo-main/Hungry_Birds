import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
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
