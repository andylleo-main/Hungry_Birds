"""Making sure somebody can administer a freshly deployed instance.

Without this a new deployment is a closed loop: the admin panel needs an admin,
promote_admin.py only promotes a user who has already signed in, signing in needs
an OTP email, and setting up email is itself something you do as an admin. The
first account has to come from outside that loop.
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.user import User, UserRole
from app.modules.auth.service import normalize_email

logger = logging.getLogger("uvicorn.error")


async def ensure_bootstrap_admin(settings: Settings, db: AsyncSession) -> None:
    """Grant the admin role to BOOTSTRAP_ADMIN_EMAIL, creating the account if needed.

    Idempotent, so it is safe on every boot and on every replica. Grants the role
    and nothing else: no password is set and no session is issued, so this alone
    does not let anybody in - they still need either an OTP or ADMIN_PASSWORD_HASH.

    Never raises. A failure here must not stop the API serving; it is reported and
    the deployment carries on, because an instance nobody can administer is still
    better than an instance that will not start.
    """
    if not settings.bootstrap_admin_email:
        return

    try:
        email = normalize_email(settings.bootstrap_admin_email)
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

        if user is None:
            db.add(User(email=email, role=UserRole.ADMIN))
            try:
                await db.commit()
            except IntegrityError:
                # Another replica booted at the same moment and won the insert.
                # Fall through and promote whatever is there now.
                await db.rollback()
                user = (
                    await db.execute(select(User).where(User.email == email))
                ).scalar_one_or_none()
                if user is None:
                    raise
            else:
                logger.warning(
                    "BOOTSTRAP_ADMIN_EMAIL: created %s as an admin. Unset the variable "
                    "once you can sign in.",
                    email,
                )
                return

        if user.role is not UserRole.ADMIN:
            previous = user.role
            user.role = UserRole.ADMIN
            await db.commit()
            logger.warning(
                "BOOTSTRAP_ADMIN_EMAIL: promoted %s from %s to admin.", email, previous.value
            )
    except Exception:
        logger.exception("BOOTSTRAP_ADMIN_EMAIL could not be applied")
        await db.rollback()
