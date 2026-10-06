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


# The settings every test runs against: the real ones, plus a configured
# payment gateway. Orders cannot be placed without one - that is the point of the
# 503 in place_order - so this is the normal state of a working deployment rather
# than a convenience. Tests that need payments switched off use `payments_off`.
def _test_settings():
    from app.core.config import get_settings

    return get_settings().model_copy(
        update={
            "razorpay_key_id": "rzp_test_FAKE",
            "razorpay_key_secret": "test-key-secret",
            # Deliberately a different value from the key secret. The two are
            # separate settings precisely because mixing them up fails closed,
            # and a fixture that used one string for both would never catch it.
            "razorpay_webhook_secret": "test-webhook-secret",
            "public_base_url": "https://testserver",
        }
    )


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

    from app.core.config import get_settings

    configured = _test_settings()
    app.dependency_overrides[get_settings] = lambda: configured

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver/api"
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_settings, None)


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
    from app.modules.orders.service import allocate_token

    async def _pay(order_id):
        order = await db.get(Order, _uuid.UUID(str(order_id)))
        order.payment_status = PaymentStatus.PAID
        if order.status == OrderStatus.AWAITING_PAYMENT:
            order.status = OrderStatus.PLACED
            # Entering the queue is what earns a token number, so a fixture that
            # claims to be apply_payment_success has to do this too. Leaving it
            # out would give every test an order the stall could not call out.
            await allocate_token(order, db)
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
def payments_on(client):
    """The configured settings the client fixture is already using.

    Kept as a fixture because tests need the secret to sign a webhook with.
    """
    return _test_settings()


@pytest.fixture
def payments_off(client):
    """Put the deployment back into its unconfigured state for one test."""
    from app.core.config import get_settings
    from app.main import app

    bare = get_settings().model_copy(
        update={
            "razorpay_key_id": "",
            "razorpay_key_secret": "",
            "razorpay_webhook_secret": "",
        }
    )
    app.dependency_overrides[get_settings] = lambda: bare
    yield bare
    app.dependency_overrides[get_settings] = lambda: _test_settings()


@pytest.fixture
def mock_payments(client):
    """Run one test with PAYMENTS_MODE=mock and no Razorpay credentials.

    Both halves matter. Mock mode is meant to work *without* a gateway, so a
    fixture that left the test keys in place would never catch a path that still
    reaches for them - and the webhook's gate is the signing secret
    specifically, which only an empty one exercises.
    """
    from app.core.config import get_settings
    from app.main import app

    mocked = get_settings().model_copy(
        update={
            "payments_mode": "mock",
            "razorpay_key_id": "",
            "razorpay_key_secret": "",
            "razorpay_webhook_secret": "",
        }
    )
    app.dependency_overrides[get_settings] = lambda: mocked
    yield mocked
    app.dependency_overrides[get_settings] = lambda: _test_settings()


@pytest.fixture
def signed_webhook(client, payments_on):
    """POST a Razorpay webhook with a real signature over the exact bytes sent.

    Signing the serialised bytes - rather than letting httpx re-encode a dict -
    is the point: the signature covers what Razorpay actually sent, and a test
    that lets the client re-serialise would pass while the production path
    failed.

    Each call gets a fresh X-Razorpay-Event-Id, because that header is the
    idempotency key. Razorpay sends no timestamp, so unlike the Cashfree webhook
    this replaces there is no staleness window - the ledger row is the only
    replay protection, which is why a test that wants a duplicate has to pass the
    same event_id back deliberately.
    """
    import hashlib
    import hmac
    import json
    import uuid as _uuid

    async def _post(
        body: dict,
        *,
        signature: str | None = None,
        event_id: str | None = None,
        secret: str | None = None,
    ):
        raw = json.dumps(body, separators=(",", ":")).encode()
        if signature is None:
            key = secret if secret is not None else payments_on.razorpay_webhook_secret
            signature = hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()
        return await client.post(
            "/payments/razorpay/webhook",
            content=raw,
            headers={
                "content-type": "application/json",
                "x-razorpay-signature": signature,
                "x-razorpay-event-id": event_id or _uuid.uuid4().hex,
            },
        )

    return _post


@pytest.fixture
def stub_razorpay(monkeypatch):
    """Answer Razorpay's calls without leaving the machine.

    Patching the client rather than inserting a payments row directly means the
    tests still go through the real /payment-session endpoint - its ownership
    check, its stall-still-open check, and the row it writes.

    Returns a dict of the calls made, so a test can assert what was attempted
    without reaching the network. `refunds` is the one that matters: Razorpay
    mints refund ids rather than accepting ours, so "how many times was refund
    called" is now a correctness question about money rather than a detail.

    `existing_refunds` is what list_refunds will report. Leaving it empty is the
    normal case; putting something in it is how a test stands in for an earlier
    attempt that got through, which attempt_refund must adopt instead of creating
    a second refund.

    Every stub yields to the event loop before answering. That is not padding: a
    stub that returns without awaiting never suspends its caller, so one worker
    runs its whole transaction - row lock, gateway call and commit - before a
    concurrent one's query even reaches Postgres. Tests about two workers racing
    would then pass or fail on nothing, which is how the refund lock looked
    broken when it was not.
    """
    import asyncio

    from app.modules.payments import razorpay

    async def _like_a_network_call():
        await asyncio.sleep(0.05)

    calls: dict = {"refunds": [], "orders": [], "qrs": [], "existing_refunds": []}

    async def fake_create_order(*, receipt, amount, notes, settings):
        await _like_a_network_call()
        calls["orders"].append({"receipt": receipt, "amount": amount, "notes": notes})
        return {
            "id": f"order_{uuid.uuid4().hex[:14]}",
            "entity": "order",
            "amount": razorpay.to_paise(amount),
            "currency": "INR",
            "receipt": receipt,
            "status": "created",
        }

    async def fake_list_refunds(payment_id, settings):
        await _like_a_network_call()
        return list(calls["existing_refunds"])

    async def fake_refund(*, payment_id, amount, notes, settings):
        await _like_a_network_call()
        calls["refunds"].append(
            {"payment_id": payment_id, "amount": amount, "notes": notes}
        )
        return {
            "id": f"rfnd_{uuid.uuid4().hex[:14]}",
            "entity": "refund",
            "amount": razorpay.to_paise(amount),
            "payment_id": payment_id,
            "status": "processed",
        }

    async def fake_order_payments(gateway_order_id, settings):
        await _like_a_network_call()
        return []

    async def fake_create_upi_qr(*, amount, description, notes, settings):
        await _like_a_network_call()
        qr = {
            "id": f"qr_{uuid.uuid4().hex[:14]}",
            "entity": "qr_code",
            "image_url": "https://rzp.io/i/testqr",
            "payment_amount": razorpay.to_paise(amount),
            "status": "active",
            "notes": notes,
        }
        calls["qrs"].append(qr)
        return qr

    async def fake_close_upi_qr(qr_id, settings):
        await _like_a_network_call()
        return None

    async def fake_fetch_qr_image(image_url):
        """The QR picture, without leaving the machine.

        Stubbed because the real one would otherwise make a genuine outbound
        request to the fake image_url above on every test that mints a QR -
        slow, dependent on the network, and it logged a 403 into the output of
        tests that had nothing to do with it.
        """
        await _like_a_network_call()
        return b"\x89PNG\r\n\x1a\n-stub"

    monkeypatch.setattr(razorpay, "create_order", fake_create_order)
    monkeypatch.setattr(razorpay, "list_refunds", fake_list_refunds)
    monkeypatch.setattr(razorpay, "refund", fake_refund)
    monkeypatch.setattr(razorpay, "order_payments", fake_order_payments)
    monkeypatch.setattr(razorpay, "create_upi_qr", fake_create_upi_qr)
    monkeypatch.setattr(razorpay, "close_upi_qr", fake_close_upi_qr)
    monkeypatch.setattr(razorpay, "fetch_qr_image", fake_fetch_qr_image)
    return calls
