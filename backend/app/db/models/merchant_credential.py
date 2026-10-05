import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MerchantCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A stall owner's password, so they are not waiting on an inbox each shift.

    A separate table rather than a column on `users`, and that is the whole
    design decision here.

    `users` deliberately has no password column. The Rider model's docstring says
    why at length: the admin's hash lives in an environment variable "precisely so
    credentials stay out of the table", and riders got their own table rather than
    reverse that for every account in the system. The same reasoning applies
    again. Customers and admins are structurally unaffected by this - there is no
    column on their row that could be set, read, leaked in a serialisation, or
    left behind by a half-finished migration.

    It also fails closed. A user with no row here simply cannot sign in with a
    password; the login route finds nothing and answers the same 401 it gives an
    unknown address. Nothing has to remember to check a flag.

    There is no `login_id`. The login id is the email, which `users` already holds
    unique and indexed - a stall owner has one less thing to be given, lose, and
    ask for again.

    Revocation is by session rather than by a credential version, unlike riders.
    Merchants hold ordinary `user_sessions` rows with refresh tokens, so changing
    a password revokes them through machinery that already exists instead of
    adding a claim to every web token in the system.
    """

    __tablename__ = "merchant_credentials"

    # One row per account, which the unique constraint enforces rather than
    # convention. ON DELETE CASCADE because a deleted account must not leave a
    # usable credential behind.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    # scrypt, self-describing: "scrypt$n$r$p$salt$key". See auth/passwords.py -
    # the format carries its own work factor so it can be raised later without
    # stranding every hash written before the change.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
