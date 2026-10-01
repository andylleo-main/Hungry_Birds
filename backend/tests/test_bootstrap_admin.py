"""BOOTSTRAP_ADMIN_EMAIL: the way the first admin exists at all.

Without it a fresh deployment is a closed loop - the admin panel needs an admin,
promote_admin.py only promotes someone who has already signed in, signing in needs
an OTP email, and configuring email is an admin task. This is privilege-granting
code, so what it does and does not do is pinned here.
"""

import uuid

import pytest

pytest.importorskip("httpx")


def _settings(email: str):
    from app.core.config import get_settings

    return get_settings().model_copy(update={"bootstrap_admin_email": email})


async def test_it_creates_the_account_when_nobody_has_signed_in(db):
    """The case it exists for: an empty users table and no way to send email."""
    from sqlalchemy import select

    from app.core.bootstrap import ensure_bootstrap_admin
    from app.db.models.user import User, UserRole

    email = f"boot.{uuid.uuid4().hex[:10]}@bitmesra.ac.in"
    await ensure_bootstrap_admin(_settings(email), db)

    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    assert user.role is UserRole.ADMIN


async def test_it_promotes_an_existing_account(db):
    from sqlalchemy import select

    from app.core.bootstrap import ensure_bootstrap_admin
    from app.db.models.user import User, UserRole

    email = f"boot.{uuid.uuid4().hex[:10]}@bitmesra.ac.in"
    db.add(User(email=email, role=UserRole.CUSTOMER, full_name="Already Here"))
    await db.commit()

    await ensure_bootstrap_admin(_settings(email), db)

    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    assert user.role is UserRole.ADMIN
    # Promoted in place rather than replaced - their orders and sessions survive.
    assert user.full_name == "Already Here"


async def test_running_it_twice_changes_nothing(db):
    """It runs on every boot and on every replica, so it has to be idempotent."""
    from sqlalchemy import select

    from app.core.bootstrap import ensure_bootstrap_admin
    from app.db.models.user import User

    email = f"boot.{uuid.uuid4().hex[:10]}@bitmesra.ac.in"
    settings = _settings(email)
    await ensure_bootstrap_admin(settings, db)
    await ensure_bootstrap_admin(settings, db)

    rows = (await db.execute(select(User).where(User.email == email))).scalars().all()
    assert len(rows) == 1


async def test_it_does_nothing_when_unset(db):
    """The default. Nobody is granted anything by leaving the variable alone."""
    from sqlalchemy import func, select

    from app.core.bootstrap import ensure_bootstrap_admin
    from app.db.models.user import User, UserRole

    before = (
        await db.execute(select(func.count()).select_from(User).where(User.role == UserRole.ADMIN))
    ).scalar_one()

    await ensure_bootstrap_admin(_settings(""), db)

    after = (
        await db.execute(select(func.count()).select_from(User).where(User.role == UserRole.ADMIN))
    ).scalar_one()
    assert before == after


async def test_it_grants_the_role_and_nothing_else(db):
    """It does not log anybody in.

    The account it makes still needs an OTP or ADMIN_PASSWORD_HASH to be used, so
    setting the variable alone is not a way into the admin panel.
    """
    from sqlalchemy import select

    from app.core.bootstrap import ensure_bootstrap_admin
    from app.db.models.session import UserSession
    from app.db.models.user import User

    email = f"boot.{uuid.uuid4().hex[:10]}@bitmesra.ac.in"
    await ensure_bootstrap_admin(_settings(email), db)

    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    sessions = (
        await db.execute(select(UserSession).where(UserSession.user_id == user.id))
    ).scalars().all()
    assert sessions == []


async def test_a_broken_bootstrap_does_not_stop_the_app(db, monkeypatch):
    """An instance nobody can administer still beats an instance that will not boot,
    so this swallows its own failures."""
    from app.core import bootstrap

    def explode(_):
        raise RuntimeError("normalisation blew up")

    monkeypatch.setattr(bootstrap, "normalize_email", explode)
    # No exception escapes.
    await bootstrap.ensure_bootstrap_admin(_settings("whoever@bitmesra.ac.in"), db)


async def test_the_admin_door_opens_for_a_bootstrapped_account(client, db):
    """End to end: bootstrap the account, then sign in with the admin password.

    This is the whole point - a deployment with no working email is still
    administerable.
    """
    from app.core.bootstrap import ensure_bootstrap_admin
    from app.core.config import get_settings
    from app.main import app
    from app.modules.auth.passwords import hash_password

    email = f"boot.{uuid.uuid4().hex[:10]}@bitmesra.ac.in"
    password = "a-long-enough-test-password"

    await ensure_bootstrap_admin(_settings(email), db)

    configured = get_settings().model_copy(
        update={"admin_password_hash": hash_password(password)}
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        r = await client.post(
            "/auth/admin/login", json={"email": email, "password": password}
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "admin"
