import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.db.models.vendor import Vendor


class Rider(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Somebody who carries a stall's orders, employed by that stall.

    Deliberately not a fourth value on UserRole, and the reasons are worth
    keeping:

    - Riders sign in with an id, not an email. `users.email` is unique and NOT
      NULL, so putting them there would mean either inventing fake addresses
      that leak into every client's AppUser, or relaxing a column half the
      codebase relies on.
    - `users` deliberately has no password column - the admin's hash lives in an
      environment variable precisely so credentials stay out of the table.
      Riders need one in the database; putting it on `users` would reverse that
      decision for every account in the system.
    - A rider belongs to exactly one stall. That is a real foreign key here; on
      `users` it would be a nullable column meaningful for one role only.
    - Most importantly, a new role fails *open*. Plenty of endpoints take any
      authenticated user, so adding a role silently admits it everywhere nobody
      thought about roles, and a review cannot see that. A separate table fails
      closed by construction: a rider is not a User, so every existing endpoint
      rejects a rider token with no change at all.
    """

    __tablename__ = "riders"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Unique across every stall, not just within one, so signing in needs only
    # an id and a password - no "which stall do you work for?" step before a
    # rider can start their shift.
    login_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)

    display_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # E.164. Required, because this is the number the customer's "call rider"
    # button dials - a rider without one is a delivery nobody can follow up.
    phone: Mapped[str] = mapped_column(String(20), nullable=False)

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Bumped whenever the password is regenerated, and carried in the rider's
    # token, so regenerating actually signs the old device out. Without it a
    # rider who quit would keep a working token until it expired, and
    # "regenerate" would be theatre.
    credential_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Kept rather than deleted when someone leaves, so their past deliveries
    # still have a name attached.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    vendor: Mapped["Vendor"] = relationship(lazy="raise")
