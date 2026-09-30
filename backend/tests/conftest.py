"""Shared fixtures for endpoint-level tests.

The suite had none of this: every test was a unit test of a pure function, so a
green run said nothing about whether the API actually refuses an order from a
vendor account or accepts a delivery to a location a stall has switched off.
These fixtures drive the real ASGI app against a real Postgres and Redis, which
is the only way those rules get checked.
"""

import uuid

import pytest

pytest.importorskip("httpx")
pytest.importorskip("sqlalchemy.ext.asyncio")

INSTITUTE = "bitmesra.ac.in"


@pytest.fixture
async def db():
    """A real Postgres session. Skips, rather than fails, with no database."""
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


@pytest.fixture
async def client():
    """The app, over ASGI, with the per-address rate limits cleared first.

    Every test shares one per-IP bucket, and not for a fixable reason: under
    ASGITransport there is no client address at all, and a forwarded header does
    not help either because TRUSTED_PROXY_COUNT is 0 for a local run, so
    ratelimit.client_ip deliberately ignores it. Without clearing, a test would
    pass or fail on how many ran before it in the same minute - the vendor signup
    route allows three requests a minute - and the failure would look like a bug
    in whichever test happened to be unlucky.

    The limiter's own counters are dropped rather than the limits being raised,
    so tests run against the real production numbers. Anything asserting *on*
    rate limiting builds its own counters afterwards and is unaffected.
    """
    import httpx

    from app.core.redis import get_redis
    from app.main import app

    redis = get_redis()
    try:
        await redis.ping()
    except Exception:
        pytest.skip("needs a reachable Redis")

    keys = [k async for k in redis.scan_iter(match="rl:*", count=500)]
    if keys:
        await redis.delete(*keys)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver/api"
    ) as ac:
        yield ac


def _token(user_id, audience):
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(str(user_id), audience)}"}


@pytest.fixture
async def customer(db):
    """A signed-in institute customer, with a phone so they can order."""
    from app.core.security import TokenAudience
    from app.db.models.user import User, UserRole

    user = User(
        email=f"stu.{uuid.uuid4().hex[:10]}@{INSTITUTE}",
        role=UserRole.CUSTOMER,
        full_name="Test Student",
        phone="+919876543210",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, _token(user.id, TokenAudience.WEB)


@pytest.fixture
async def vendor(db):
    """An approved, open stall and a merchant-app token for its owner."""
    from app.core.security import TokenAudience
    from app.db.models.user import User, UserRole
    from app.db.models.vendor import Vendor

    user = User(email=f"stall.{uuid.uuid4().hex[:10]}@gmail.com", role=UserRole.VENDOR)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    v = Vendor(
        user_id=user.id,
        stall_name=f"Stall {uuid.uuid4().hex[:5]}",
        is_approved=True,
        is_open=True,
    )
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v, _token(user.id, TokenAudience.MERCHANT)


@pytest.fixture
async def menu_item(db, vendor):
    """One available dish at the stall, priced so totals are easy to read."""
    from decimal import Decimal

    from app.db.models.menu import MenuItem

    v, _ = vendor
    item = MenuItem(
        vendor_id=v.id, name="Momos", price=Decimal("60.00"), is_available=True
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item
