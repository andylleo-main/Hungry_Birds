from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One signed-in device, and the refresh token that keeps it signed in.

    Refresh tokens used to be JWTs, which meant nothing could ever take one
    back: signing out cleared the browser's copy and the token itself stayed
    valid for its full thirty days. Anyone who had captured it kept a working
    key to the account. Holding sessions here makes a refresh token a claim on
    a row, so revoking the row ends it immediately.
    """

    __tablename__ = "user_sessions"

    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Only the hash is stored. A leaked database backup then yields nothing
    # usable, the same reason passwords are not kept in plaintext.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    # The hash this session had before its last rotation. A refresh arriving
    # with this value means the old token was replayed - it was stolen, or
    # copied - so the whole session is destroyed rather than renewed. Without
    # keeping it, a replay would simply look like an unknown token and the
    # theft would go unnoticed.
    previous_token_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Shown on the "where you're signed in" list so someone can recognise a
    # device they don't know and end it.
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User"] = relationship(lazy="raise")
