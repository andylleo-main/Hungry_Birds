import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Vendor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "vendors"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    stall_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_open: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # How this stall will hand food over. Both default to True so an existing
    # stall keeps working the moment this ships - it could already be eaten at
    # the counter, and delivery is the new capability being offered, not one
    # the vendor has to opt into before their stall reappears.
    dine_in_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    delivery_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship(back_populates="vendor")
    categories: Mapped[list["MenuCategory"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan", order_by="MenuCategory.sort_order"
    )
    items: Mapped[list["MenuItem"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan"
    )
    disabled_locations: Mapped[list["VendorDisabledLocation"]] = relationship(
        back_populates="vendor", cascade="all, delete-orphan", lazy="raise"
    )


class VendorDisabledLocation(Base):
    """One campus location a stall has switched *off*.

    Storing the exceptions rather than the choices is what makes "every location
    is on by default" true without any seeding: a stall with no rows here
    delivers everywhere, so nothing has to be written when a vendor is created
    and nothing had to be backfilled for the stalls that existed before delivery
    did. Switching a location off inserts a row, switching it back on deletes
    one.

    No UUID primary key - the pair *is* the identity, and a composite key makes
    a duplicate row impossible at the database rather than only in the handler.
    """

    __tablename__ = "vendor_disabled_locations"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # A code from app.core.locations.DELIVERY_LOCATIONS. Not a database enum:
    # the catalogue is expected to gain entries, and an enum would turn adding a
    # building into a migration.
    code: Mapped[str] = mapped_column(String(32), primary_key=True)

    vendor: Mapped["Vendor"] = relationship(back_populates="disabled_locations")
