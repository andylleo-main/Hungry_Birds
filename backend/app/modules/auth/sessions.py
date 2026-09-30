"""Server-side sessions: issuing, rotating and revoking refresh tokens.

The refresh token is an opaque random string rather than a JWT. A JWT carries
its own validity, so the only way to end one early is to wait for it to expire
- which is why signing out previously did nothing but clear the browser's copy.
An opaque token is just a lookup key: the session row decides whether it still
works, so revoking is immediate and real.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.session import UserSession

# 32 bytes of randomness: far beyond guessing, and short enough to sit in a
# header without complaint.
TOKEN_BYTES = 32


def _hash(token: str) -> str:
    """SHA-256, not bcrypt.

    Password hashing is deliberately slow because passwords are low-entropy and
    guessable. These tokens are 256 bits of CSPRNG output, so there is nothing
    to guess and slowness would only tax every refresh. What matters is that
    the stored form is useless if the database leaks, which a plain digest
    gives us.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_session(
    user_id: uuid.UUID,
    db: AsyncSession,
    *,
    lifetime_days: int,
    user_agent: str | None = None,
    audience: str | None = None,
) -> tuple[UserSession, str]:
    """Start a session. Returns the row and the raw token, which is the only
    time the raw value exists - afterwards only its hash is stored."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = _now()
    session = UserSession(
        user_id=user_id,
        token_hash=_hash(token),
        expires_at=now + timedelta(days=lifetime_days),
        last_used_at=now,
        user_agent=(user_agent or "")[:255] or None,
        audience=audience,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session, token


class SessionRejected(Exception):
    """The token is unknown, expired, revoked, or was replayed."""


async def rotate_session(token: str, db: AsyncSession) -> tuple[UserSession, str]:
    """Exchange a refresh token for a fresh one, keeping the same session.

    Rotation matters because a refresh token is long-lived by design. Issuing a
    new one on every use means a stolen copy is only good until the real client
    next refreshes - and when that happens, the theft becomes visible instead of
    silent, because the thief's next attempt arrives with a token this session
    has already retired.
    """
    digest = _hash(token)

    result = await db.execute(select(UserSession).where(UserSession.token_hash == digest))
    session = result.scalar_one_or_none()

    if session is None:
        # Not the current token. If it is the one this session just replaced,
        # two parties hold the same token and one of them should not - so end
        # the session rather than quietly issuing the attacker a new one.
        replayed = await db.execute(
            select(UserSession).where(UserSession.previous_token_hash == digest)
        )
        stolen = replayed.scalar_one_or_none()
        if stolen is not None and stolen.revoked_at is None:
            stolen.revoked_at = _now()
            await db.commit()
        raise SessionRejected("unknown refresh token")

    now = _now()
    if session.revoked_at is not None:
        raise SessionRejected("session revoked")
    if session.expires_at <= now:
        raise SessionRejected("session expired")

    new_token = secrets.token_urlsafe(TOKEN_BYTES)
    session.previous_token_hash = session.token_hash
    session.token_hash = _hash(new_token)
    session.last_used_at = now
    await db.commit()
    await db.refresh(session)
    return session, new_token


async def revoke_session(token: str, db: AsyncSession) -> bool:
    """End the session this token belongs to. True if one was actually ended.

    Accepts the current token or the one it just replaced, so a sign-out that
    races an in-flight refresh still signs the user out instead of silently
    failing.
    """
    digest = _hash(token)
    result = await db.execute(
        select(UserSession).where(
            (UserSession.token_hash == digest) | (UserSession.previous_token_hash == digest)
        )
    )
    session = result.scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        return False
    session.revoked_at = _now()
    await db.commit()
    return True


async def revoke_all_for_user(user_id: uuid.UUID, db: AsyncSession) -> int:
    """Sign out every device. The button you want after losing a phone."""
    result = await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()
    return result.rowcount or 0


async def revoke_by_id(
    session_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession
) -> bool:
    """Revoke one session, scoped to its owner so nobody can end someone else's."""
    result = await db.execute(
        select(UserSession).where(
            UserSession.id == session_id, UserSession.user_id == user_id
        )
    )
    session = result.scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        return False
    session.revoked_at = _now()
    await db.commit()
    return True


async def list_active(user_id: uuid.UUID, db: AsyncSession) -> list[UserSession]:
    result = await db.execute(
        select(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > _now(),
        )
        .order_by(UserSession.last_used_at.desc())
    )
    return list(result.scalars().all())
