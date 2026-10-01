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


@pytest.fixture
def pay(db):
    """Mark an order paid, the way the Cashfree webhook would.

    Orders now start in awaiting_payment and no stall can see them until money
    arrives, so most tests about what a stall or rider does need the order to be
    paid for first. This does exactly what apply_payment_success does, and
    nothing more, so a test that uses it is not quietly skipping a rule.
    """
    import uuid as _uuid

    from app.db.models.order import Order, OrderStatus
    from app.db.models.payment import PaymentStatus

    async def _pay(order_id):
        order = await db.get(Order, _uuid.UUID(str(order_id)))
        order.payment_status = PaymentStatus.PAID
        if order.status == OrderStatus.AWAITING_PAYMENT:
            order.status = OrderStatus.PLACED
        await db.commit()
        return order

    return _pay


@pytest.fixture
async def rider(client, vendor):
    """A rider of the fixture stall, plus a signed-in rider-app token.

    Created through the API rather than the database so the password is a real
    generated one and the login path is the one under test.
    """
    v, headers = vendor
    r = await client.post(
        "/vendors/me/riders",
        headers=headers,
        json={"display_name": "Ravi Kumar", "phone": "9876500011"},
    )
    assert r.status_code == 201, r.text
    created = r.json()

    login = await client.post(
        "/auth/rider/login",
        json={"login_id": created["login_id"], "password": created["password"]},
    )
    assert login.status_code == 200, login.text
    return created, {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
async def delivery_order(client, customer, vendor, menu_item, pay):
    """A paid delivery order at the fixture stall, ready to be assigned."""
    user, headers = customer
    v, _ = vendor
    r = await client.post(
        "/orders",
        headers=headers,
        json={
            "vendor_id": str(v.id),
            "items": [{"menu_item_id": str(menu_item.id), "quantity": 1}],
            "fulfilment_type": "delivery",
            "delivery_location": "hostel_5",
        },
    )
    assert r.status_code == 201, r.text
    await pay(r.json()["id"])
    # Re-read, so the caller sees the order as the stall does.
    fresh = await client.get(f"/orders/{r.json()['id']}", headers=headers)
    return fresh.json()


@pytest.fixture
def payments_on():
    """Switch Cashfree on for the duration of a test, with a known secret.

    Overrides the dependency rather than the environment, so the real settings
    object is untouched and nothing leaks into the next test.
    """
    from app.core.config import Settings, get_settings
    from app.main import app

    configured = get_settings().model_copy(
        update={
            "cashfree_app_id": "TEST_APP_ID",
            "cashfree_secret_key": "test-secret-key",
            "cashfree_env": "sandbox",
            "public_base_url": "https://testserver",
        }
    )

    def _override() -> Settings:
        return configured

    app.dependency_overrides[get_settings] = _override
    yield configured
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def signed_webhook(client, payments_on):
    """POST a Cashfree webhook with a real signature over the exact bytes sent.

    Signing the serialised bytes - rather than letting httpx re-encode a dict -
    is the point: the signature covers what Cashfree actually sent, and a test
    that lets the client re-serialise would pass while the production path
    failed.
    """
    import base64
    import hashlib
    import hmac
    import json
    import time

    async def _post(body: dict, *, timestamp: str | None = None, signature: str | None = None):
        raw = json.dumps(body, separators=(",", ":")).encode()
        ts = timestamp if timestamp is not None else str(int(time.time()))
        if signature is None:
            digest = hmac.new(
                payments_on.cashfree_secret_key.encode(), ts.encode() + raw, hashlib.sha256
            ).digest()
            signature = base64.b64encode(digest).decode()
        return await client.post(
            "/payments/cashfree/webhook",
            content=raw,
            headers={
                "content-type": "application/json",
                "x-webhook-timestamp": ts,
                "x-webhook-signature": signature,
            },
        )

    return _post


@pytest.fixture
def stub_cashfree(monkeypatch):
    """Answer Cashfree's create-order call without leaving the machine.

    Patching the client rather than inserting a payments row directly means the
    tests still go through the real /payment-session endpoint - its ownership
    check, its stall-still-open check, and the row it writes.

    Returns the list of refund calls made, so a test can assert one was
    attempted without reaching the network.
    """
    from app.modules.payments import cashfree

    refunds: list[dict] = []

    async def fake_create_order(*, cf_order_id, amount, **kwargs):
        return {
            "cf_order_id": cf_order_id,
            "order_status": "ACTIVE",
            "payment_session_id": f"session_{cf_order_id}",
        }

    async def fake_refund(**kwargs):
        refunds.append(kwargs)
        return {"refund_status": "PENDING"}

    monkeypatch.setattr(cashfree, "create_order", fake_create_order)
    monkeypatch.setattr(cashfree, "refund", fake_refund)
    return refunds
