import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class VendorDevice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One phone signed into the merchant app, and where to push to it.

    A stall is often two devices - the owner's phone and a tablet by the fryer -
    so this is a list per vendor rather than a column on `vendors`.

    The token is unique across the whole table, not per vendor, because Firebase
    issues it per app install: if a phone is handed to a different stall and
    signed in again, the same token must move to the new vendor rather than
    quietly pushing one stall's orders to another's screen.
    """

    __tablename__ = "vendor_devices"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # FCM registration tokens are long and have no documented ceiling; 512 is
    # comfortably above anything observed and bounded enough to index.
    fcm_token: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)

    platform: Mapped[str] = mapped_column(String(16), default="android", nullable=False)

    # Refreshed whenever the app re-registers, so a device that has not been
    # seen in months can be cleared out without guessing from created_at.
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    vendor: Mapped["Vendor"] = relationship(lazy="raise")


class RiderDevice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A rider's phone, for "you have a delivery" notifications.

    Its own table rather than a nullable owner column on VendorDevice above.
    Riders are already their own table for the same reason - a rider is not a
    user - and a shared table would need a check constraint and a branch at every
    read to express a relationship two foreign keys already state plainly.

    Everything else matches VendorDevice: the token is unique across the table
    because Firebase issues one per app install, so a phone passed between riders
    has to move with it rather than buzz for both.
    """

    __tablename__ = "rider_devices"

    rider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("riders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    fcm_token: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(16), default="android", nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    rider: Mapped["Rider"] = relationship(lazy="raise")
