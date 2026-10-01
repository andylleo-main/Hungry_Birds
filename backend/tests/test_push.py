"""Push notifications: device registration, and failing safely.

The rule that matters most here is the negative one - a stall gets its orders
over the websocket and on every queue fetch, so push is a convenience. Firebase
being slow, broken or misconfigured must never be able to fail somebody's order.
"""

import uuid

import pytest

pytest.importorskip("httpx")

TOKEN_A = "fcm-token-" + "a" * 40
TOKEN_B = "fcm-token-" + "b" * 40


def _push_settings():
    """Settings with push switched on, without touching the real environment."""
    from app.core.config import get_settings

    return get_settings().model_copy(
        update={
            "fcm_project_id": "test-project",
            "firebase_service_account_json": '{"type": "service_account"}',
        }
    )


# --- registration -----------------------------------------------------------


async def test_a_stall_registers_a_phone(client, vendor):
    v, headers = vendor
    r = await client.post(
        "/vendors/me/devices", headers=headers, json={"fcm_token": TOKEN_A}
    )
    assert r.status_code == 201, r.text
    assert r.json() == {"fcm_token": TOKEN_A, "platform": "android"}


async def test_registering_the_same_token_twice_does_not_duplicate_it(client, db, vendor):
    """The app re-registers on every start, so this is the common path."""
    from sqlalchemy import func, select

    from app.db.models.device import VendorDevice

    v, headers = vendor
    token = f"fcm-{uuid.uuid4().hex}" + "x" * 20

    for _ in range(3):
        r = await client.post("/vendors/me/devices", headers=headers, json={"fcm_token": token})
        assert r.status_code == 201, r.text

    count = await db.execute(
        select(func.count()).select_from(VendorDevice).where(VendorDevice.fcm_token == token)
    )
    assert count.scalar_one() == 1


async def test_a_phone_that_signs_into_another_stall_stops_buzzing_for_the_first(
    client, db, vendor
):
    """Firebase issues one token per install, so the token has to move."""
    from sqlalchemy import select

    from app.core.security import TokenAudience, create_access_token
    from app.db.models.device import VendorDevice
    from app.db.models.user import User, UserRole
    from app.db.models.vendor import Vendor

    v, headers = vendor
    token = f"fcm-{uuid.uuid4().hex}" + "y" * 20
    assert (
        await client.post("/vendors/me/devices", headers=headers, json={"fcm_token": token})
    ).status_code == 201

    other_user = User(email=f"other.{uuid.uuid4().hex[:8]}@gmail.com", role=UserRole.VENDOR)
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)
    other = Vendor(user_id=other_user.id, stall_name="Second", is_approved=True, is_open=True)
    db.add(other)
    await db.commit()
    await db.refresh(other)
    other_headers = {
        "Authorization": f"Bearer {create_access_token(str(other_user.id), TokenAudience.MERCHANT)}"
    }

    assert (
        await client.post("/vendors/me/devices", headers=other_headers, json={"fcm_token": token})
    ).status_code == 201

    rows = await db.execute(select(VendorDevice).where(VendorDevice.fcm_token == token))
    devices = rows.scalars().all()
    assert len(devices) == 1
    assert devices[0].vendor_id == other.id


async def test_signing_out_stops_the_pushes(client, vendor):
    v, headers = vendor
    token = f"fcm-{uuid.uuid4().hex}" + "z" * 20
    await client.post("/vendors/me/devices", headers=headers, json={"fcm_token": token})

    r = await client.delete(f"/vendors/me/devices/{token}", headers=headers)
    assert r.status_code == 204
    # Idempotent, so signing out twice is not an error.
    assert (await client.delete(f"/vendors/me/devices/{token}", headers=headers)).status_code == 204


async def test_a_customer_cannot_register_for_a_stalls_orders(client, customer):
    user, headers = customer
    r = await client.post("/vendors/me/devices", headers=headers, json={"fcm_token": TOKEN_B})
    assert r.status_code == 403


# --- sending ----------------------------------------------------------------


async def test_nothing_is_sent_when_firebase_is_not_configured(db, vendor, monkeypatch):
    """The default state of this repo, and of a fresh deploy."""
    from app.core.config import get_settings
    from app.modules.notifications import service

    called = False

    async def _boom(*a, **k):
        nonlocal called
        called = True

    monkeypatch.setattr(service, "send_to_token", _boom)
    v, _ = vendor
    await service.notify_new_order(uuid.uuid4(), v.id, get_settings())
    assert called is False


async def test_a_dead_token_is_dropped_after_firebase_rejects_it(
    client, db, vendor, customer, menu_item, monkeypatch
):
    """Uninstalled apps leave tokens that will never work again.

    Left alone they accumulate, and every order then pays for a round trip per
    corpse.
    """
    from sqlalchemy import select

    from app.db.models.device import VendorDevice
    from app.modules.notifications import service

    v, headers = vendor
    dead = f"fcm-dead-{uuid.uuid4().hex}" + "d" * 20
    alive = f"fcm-live-{uuid.uuid4().hex}" + "l" * 20
    for token in (dead, alive):
        assert (
            await client.post("/vendors/me/devices", headers=headers, json={"fcm_token": token})
        ).status_code == 201

    sent: list[str] = []

    async def fake_send(token, **kwargs):
        sent.append(token)
        return "UNREGISTERED" if token == dead else None

    monkeypatch.setattr(service, "send_to_token", fake_send)

    cust, cust_headers = customer
    order = (
        await client.post(
            "/orders",
            headers=cust_headers,
            json={
                "vendor_id": str(v.id),
                "items": [{"menu_item_id": str(menu_item.id), "quantity": 1}],
            },
        )
    ).json()

    await service.notify_new_order(uuid.UUID(order["id"]), v.id, _push_settings())

    assert sorted(sent) == sorted([dead, alive])

    rows = await db.execute(
        select(VendorDevice.fcm_token).where(VendorDevice.vendor_id == v.id)
    )
    remaining = set(rows.scalars().all())
    assert dead not in remaining
    assert alive in remaining


async def test_one_broken_device_does_not_silence_the_others(
    client, db, vendor, customer, menu_item, monkeypatch
):
    from app.modules.notifications import service

    v, headers = vendor
    first = f"fcm-first-{uuid.uuid4().hex}" + "1" * 20
    second = f"fcm-second-{uuid.uuid4().hex}" + "2" * 20
    for token in (first, second):
        await client.post("/vendors/me/devices", headers=headers, json={"fcm_token": token})

    reached: list[str] = []

    async def fake_send(token, **kwargs):
        if token == first:
            raise RuntimeError("firebase said no")
        reached.append(token)
        return None

    monkeypatch.setattr(service, "send_to_token", fake_send)

    cust, cust_headers = customer
    order = (
        await client.post(
            "/orders",
            headers=cust_headers,
            json={
                "vendor_id": str(v.id),
                "items": [{"menu_item_id": str(menu_item.id), "quantity": 1}],
            },
        )
    ).json()

    await service.notify_new_order(uuid.UUID(order["id"]), v.id, _push_settings())
    assert reached == [second]


async def test_placing_an_order_survives_firebase_being_broken(
    client, vendor, customer, menu_item, monkeypatch
):
    """The property this whole feature is subordinate to."""
    from app.modules.notifications import service

    v, headers = vendor
    await client.post(
        "/vendors/me/devices", headers=headers, json={"fcm_token": f"fcm-{uuid.uuid4().hex}zzzz"}
    )

    async def explode(*a, **k):
        raise RuntimeError("firebase is on fire")

    monkeypatch.setattr(service, "send_to_token", explode)

    cust, cust_headers = customer
    r = await client.post(
        "/orders",
        headers=cust_headers,
        json={
            "vendor_id": str(v.id),
            "items": [{"menu_item_id": str(menu_item.id), "quantity": 2}],
        },
    )
    assert r.status_code == 201, r.text


# --- the pieces -------------------------------------------------------------


def test_fire_and_log_swallows_and_keeps_going():
    import asyncio

    from app.core.tasks import fire_and_log

    async def boom():
        raise RuntimeError("nope")

    # Returns normally rather than propagating - that is the whole contract.
    asyncio.run(fire_and_log("test", boom))


def test_firebases_error_code_is_read_out_of_its_real_response_shape():
    """FCM buries the machine-readable reason two levels down."""
    import httpx

    from app.modules.notifications.fcm import _error_code

    response = httpx.Response(
        404,
        json={
            "error": {
                "code": 404,
                "message": "Requested entity was not found.",
                "status": "NOT_FOUND",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                        "errorCode": "UNREGISTERED",
                    }
                ],
            }
        },
        request=httpx.Request("POST", "https://fcm.googleapis.com/"),
    )
    assert _error_code(response) == "UNREGISTERED"

    # A non-JSON body must not raise on the way to being logged.
    plain = httpx.Response(
        503, text="upstream unavailable", request=httpx.Request("POST", "https://x/")
    )
    assert _error_code(plain) is None


# --- the same rule, applied to the login email ------------------------------


async def test_requesting_a_code_survives_resend_being_down(client, monkeypatch):
    """This was a real hole, not a hypothetical one.

    The Resend call sat unguarded in the middle of request_otp, so an outage at
    Resend did not merely fail to deliver one code - it made signing in return
    500 for everybody. Losing email is exactly when you least want login to break
    too.

    send_code_email is patched rather than the Resend SDK, so the test means the
    same thing whether or not this machine has a RESEND_API_KEY configured.
    """
    from app.modules.auth import service

    async def explode(*a, **k):
        raise RuntimeError("resend is down")

    monkeypatch.setattr(service, "send_code_email", explode)

    r = await client.post(
        "/auth/otp/request", json={"email": f"s.{uuid.uuid4().hex[:8]}@bitmesra.ac.in"}
    )
    assert r.status_code == 200, r.text


async def test_the_login_email_is_not_sent_on_the_event_loop(monkeypatch):
    """`resend.Emails.send` is synchronous `requests` under the hood.

    Called straight from an async handler it blocks every other request in flight
    for the length of the round trip, which on a single container is the whole
    service. It must reach Resend through a worker thread.
    """
    import threading

    from app.core.config import get_settings
    from app.modules.auth import service

    settings = get_settings().model_copy(update={"resend_api_key": "re_test"})
    loop_thread = threading.get_ident()
    ran_on: list[int] = []

    monkeypatch.setattr(
        service, "_send_code_email", lambda *a, **k: ran_on.append(threading.get_ident())
    )
    await service.send_code_email("someone@bitmesra.ac.in", "123456", settings)

    assert ran_on, "the email was never sent"
    assert ran_on[0] != loop_thread, "Resend was called on the event loop thread"
