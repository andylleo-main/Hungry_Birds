"""Session rotation and revocation.

Covered live by the audit script too, but this is the logic that decides
whether a stolen refresh token keeps working, so it gets tests that run
without a server standing up.
"""

import uuid

import pytest

from app.modules.auth.sessions import (
    SessionRejected,
    create_session,
    list_active,
    revoke_all_for_user,
    revoke_by_id,
    revoke_session,
    rotate_session,
)

sqlalchemy = pytest.importorskip("sqlalchemy.ext.asyncio")


@pytest.fixture
async def db():
    """A real Postgres session, rolled back afterwards.

    Skips rather than fails when there is no database, so the rest of the suite
    still runs on a machine that only has Python.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings

    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.rollback()
    except Exception:
        pytest.skip("needs a reachable Postgres")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _user(db):
    """A throwaway account to hang sessions off."""
    from app.db.models.user import User

    user = User(email=f"sess.{uuid.uuid4().hex[:10]}@bitmesra.ac.in")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_a_new_session_yields_a_working_token(db):
    user = await _user(db)
    session, token = await create_session(user.id, db, lifetime_days=30, user_agent="Probe/1.0")
    assert session.user_agent == "Probe/1.0"
    # The raw token is never stored, only its digest.
    assert token not in (session.token_hash, session.previous_token_hash or "")

    rotated, new_token = await rotate_session(token, db)
    assert rotated.id == session.id
    assert new_token != token


async def test_rotation_retires_the_old_token(db):
    user = await _user(db)
    _, token = await create_session(user.id, db, lifetime_days=30)
    _, second = await rotate_session(token, db)

    # The new one works...
    await rotate_session(second, db)

    # ...and the original is dead, because rotation is what bounds how long a
    # stolen copy stays useful.
    with pytest.raises(SessionRejected):
        await rotate_session(token, db)


async def test_replaying_a_retired_token_destroys_the_session(db):
    """The detection that makes rotation worth having.

    Two parties holding the same token means one of them stole it. Since we
    cannot tell which, the safe move is to end the session and make both sign
    in again - a moment's inconvenience against an open-ended intrusion.
    """
    user = await _user(db)
    _, original = await create_session(user.id, db, lifetime_days=30)
    _, current = await rotate_session(original, db)

    with pytest.raises(SessionRejected):
        await rotate_session(original, db)

    # The legitimate holder is locked out too - deliberately.
    with pytest.raises(SessionRejected):
        await rotate_session(current, db)


async def test_revoking_ends_refreshing(db):
    user = await _user(db)
    _, token = await create_session(user.id, db, lifetime_days=30)
    assert await revoke_session(token, db) is True
    with pytest.raises(SessionRejected):
        await rotate_session(token, db)
    # Idempotent: revoking again is not an error and reports nothing happened.
    assert await revoke_session(token, db) is False


async def test_an_unknown_token_revokes_nothing(db):
    assert await revoke_session("never-issued", db) is False


async def test_one_device_can_be_ended_without_touching_the_others(db):
    user = await _user(db)
    phone, phone_token = await create_session(user.id, db, lifetime_days=30, user_agent="Phone")
    _, laptop_token = await create_session(user.id, db, lifetime_days=30, user_agent="Laptop")

    assert len(await list_active(user.id, db)) == 2
    assert await revoke_by_id(phone.id, user.id, db) is True

    with pytest.raises(SessionRejected):
        await rotate_session(phone_token, db)
    await rotate_session(laptop_token, db)  # the other device is unaffected
    assert len(await list_active(user.id, db)) == 1


async def test_nobody_can_revoke_someone_elses_session(db):
    owner = await _user(db)
    stranger = await _user(db)
    session, token = await create_session(owner.id, db, lifetime_days=30)

    assert await revoke_by_id(session.id, stranger.id, db) is False
    await rotate_session(token, db)  # still alive


async def test_revoke_all_signs_out_every_device(db):
    user = await _user(db)
    tokens = [(await create_session(user.id, db, lifetime_days=30))[1] for _ in range(3)]
    assert await revoke_all_for_user(user.id, db) == 3
    for token in tokens:
        with pytest.raises(SessionRejected):
            await rotate_session(token, db)
    assert await list_active(user.id, db) == []


async def test_an_expired_session_stops_working(db):
    user = await _user(db)
    _, token = await create_session(user.id, db, lifetime_days=-1)
    with pytest.raises(SessionRejected):
        await rotate_session(token, db)
