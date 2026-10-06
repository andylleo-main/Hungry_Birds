"""Riders collecting at the door.

This reverses a rule the project held on purpose: every order used to be paid up
front, because a stall that cooks food which is never paid for eats the loss. The
exposure is back, and most of what follows is the set of things that keep it
bounded - a cash order cannot be completed while the money is still owed, it
cannot be swept away mid-cook, and it cannot trigger a gateway refund for money
no gateway ever took.
"""

import uuid

import pytest

pytest.importorskip("httpx")


def _lines(item, qty=1):
    return [{"menu_item_id": str(item.id), "quantity": qty}]


async def _cash_order(client, headers, vendor_id, item, **extra):
    r = await client.post(
        "/orders",
        headers=headers,
        json={
            "vendor_id": str(vendor_id),
            "items": _lines(item),
            "fulfilment_type": "delivery",
            "delivery_location": "hostel_3",
            "payment_method": "cod",
            **extra,
        },
    )
    return r


async def _out_for_delivery(client, db, order_id, vendor_headers, rider):
    """Walk a cash order to the doorstep, as the two apps really would."""
    rider_json, rider_headers = rider
    for status_value in ("accepted", "preparing", "ready"):
        r = await client.patch(
            f"/vendors/me/orders/{order_id}/status",
            headers=vendor_headers,
            json={"status": status_value},
        )
        assert r.status_code == 200, r.text

    assigned = await client.post(
        f"/vendors/me/orders/{order_id}/assign",
        headers=vendor_headers,
        json={"rider_id": rider_json["id"]},
    )
    assert assigned.status_code == 200, assigned.text

    picked_up = await client.patch(
        f"/rider/orders/{order_id}/status",
        headers=rider_headers,
        json={"status": "out_for_delivery"},
    )
    assert picked_up.status_code == 200, picked_up.text
    return rider_headers


# --- placing one ------------------------------------------------------------


async def test_a_cash_order_reaches_the_stall_without_a_payment(
    client, db, customer, vendor, menu_item
):
    """The whole point: no gateway step, and the stall sees it immediately.

    An online order is invisible until a webhook lands. A cash one has nothing to
    wait for, so it is placed straight into the queue - with the token number it
    earns at that moment, for the same reason an online order earns one when the
    payment lands.
    """
    from app.db.models.order import Order
    from app.db.models.payment import Payment
    from sqlalchemy import select

    _, headers = customer
    v, _ = vendor

    r = await _cash_order(client, headers, v.id, menu_item)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "placed"
    assert body["payment_status"] == "due"
    assert body["payment_method"] == "cod"
    assert body["token_number"] is not None

    # No gateway order was opened, because none was needed.
    payment = (
        await db.execute(select(Payment).where(Payment.order_id == uuid.UUID(body["id"])))
    ).scalar_one_or_none()
    assert payment is None

    row = await db.get(Order, uuid.UUID(body["id"]))
    await db.refresh(row)
    assert row.collected_via is None


async def test_the_sweep_leaves_a_cash_order_alone(client, db, customer, vendor, menu_item):
    """The trap this design exists to avoid.

    sweep_abandoned cancels awaiting_payment + pending after twenty minutes. A
    cash order parked in that pair would be cancelled mid-cook with a rider
    already assigned, so it is never in it - and this is the test that says so
    if somebody later "simplifies" placement back to one path.
    """
    from datetime import datetime, timedelta, timezone

    from app.core.config import get_settings
    from app.db.models.order import Order
    from app.modules.payments.service import sweep_abandoned

    _, headers = customer
    v, _ = vendor
    order_id = uuid.UUID((await _cash_order(client, headers, v.id, menu_item)).json()["id"])

    row = await db.get(Order, order_id)
    row.created_at = datetime.now(timezone.utc) - timedelta(hours=3)
    await db.commit()

    await sweep_abandoned(db, get_settings())

    await db.refresh(row)
    assert row.status.value == "placed"
    assert row.payment_status.value == "due"


async def test_cash_is_refused_on_a_dine_in_order(client, customer, vendor, menu_item):
    """There is nobody to collect from somebody standing at the counter."""
    _, headers = customer
    v, _ = vendor
    r = await client.post(
        "/orders",
        headers=headers,
        json={
            "vendor_id": str(v.id),
            "items": _lines(menu_item),
            "fulfilment_type": "dine_in",
            "payment_method": "cod",
        },
    )
    assert r.status_code == 422


async def test_cash_is_refused_when_the_deployment_has_it_off(
    client, customer, vendor, menu_item
):
    """COD_ENABLED is the kill switch, and it has to actually stop orders."""
    from app.core.config import get_settings
    from app.main import app

    no_cash = get_settings().model_copy(update={"cod_enabled": False})
    app.dependency_overrides[get_settings] = lambda: no_cash
    try:
        _, headers = customer
        v, _ = vendor
        r = await _cash_order(client, headers, v.id, menu_item)
        assert r.status_code == 400
        assert "pay online" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_settings, None)


async def test_an_online_order_still_defaults_without_the_field(
    stub_razorpay, client, customer, vendor, menu_item
):
    """An older client that has never heard of payment_method keeps working."""
    _, headers = customer
    v, _ = vendor
    r = await client.post(
        "/orders", headers=headers, json={"vendor_id": str(v.id), "items": _lines(menu_item)}
    )
    assert r.status_code == 201
    assert r.json()["payment_status"] == "pending"
    assert r.json()["status"] == "awaiting_payment"


# --- collecting it ----------------------------------------------------------


async def test_a_rider_cannot_complete_while_the_money_is_owed(
    client, db, customer, vendor, menu_item, rider
):
    """The single control that makes any of this safe.

    Without it a rider closes the order having collected nothing, and the stall
    has cooked food nobody paid for.
    """
    from app.db.models.order import Order

    _, headers = customer
    v, vendor_headers = vendor
    order = (await _cash_order(client, headers, v.id, menu_item)).json()
    rider_headers = await _out_for_delivery(client, db, order["id"], vendor_headers, rider)

    row = await db.get(Order, uuid.UUID(order["id"]))
    await db.refresh(row)

    r = await client.patch(
        f"/rider/orders/{order['id']}/status",
        headers=rider_headers,
        json={"status": "completed", "delivery_code": row.delivery_code},
    )
    assert r.status_code == 400
    assert "collect" in r.json()["detail"].lower()

    await db.refresh(row)
    assert row.status.value == "out_for_delivery"


async def test_collecting_cash_then_completing(client, db, customer, vendor, menu_item, rider):
    """The happy path, end to end."""
    from app.db.models.order import Order

    _, headers = customer
    v, vendor_headers = vendor
    order = (await _cash_order(client, headers, v.id, menu_item)).json()
    rider_headers = await _out_for_delivery(client, db, order["id"], vendor_headers, rider)

    collected = await client.post(
        f"/rider/orders/{order['id']}/collect",
        headers=rider_headers,
        json={"method": "cash"},
    )
    assert collected.status_code == 200, collected.text
    assert collected.json()["payment_status"] == "paid"
    assert collected.json()["collected_via"] == "cash"

    row = await db.get(Order, uuid.UUID(order["id"]))
    await db.refresh(row)

    done = await client.patch(
        f"/rider/orders/{order['id']}/status",
        headers=rider_headers,
        json={"status": "completed", "delivery_code": row.delivery_code},
    )
    assert done.status_code == 200, done.text

    await db.refresh(row)
    assert row.status.value == "completed"
    assert row.payment_status.value == "paid"
    assert row.collected_via == "cash"


async def test_collecting_twice_is_refused(client, db, customer, vendor, menu_item, rider):
    _, headers = customer
    v, vendor_headers = vendor
    order = (await _cash_order(client, headers, v.id, menu_item)).json()
    rider_headers = await _out_for_delivery(client, db, order["id"], vendor_headers, rider)

    first = await client.post(
        f"/rider/orders/{order['id']}/collect", headers=rider_headers, json={"method": "cash"}
    )
    assert first.status_code == 200

    second = await client.post(
        f"/rider/orders/{order['id']}/collect", headers=rider_headers, json={"method": "cash"}
    )
    assert second.status_code == 400
    assert "already paid" in second.json()["detail"].lower()


async def test_a_rider_cannot_collect_before_picking_the_order_up(
    client, db, customer, vendor, menu_item, rider
):
    """Collecting is something that happens at a door, not in a kitchen."""
    _, headers = customer
    v, _ = vendor
    order = (await _cash_order(client, headers, v.id, menu_item)).json()
    _rider_json, rider_headers = rider

    r = await client.post(
        f"/rider/orders/{order['id']}/collect", headers=rider_headers, json={"method": "cash"}
    )
    # 404 before assignment: it is not their order to see, let alone collect on.
    assert r.status_code in (400, 404)


async def test_a_rider_cannot_collect_on_another_riders_order(
    client, db, customer, vendor, menu_item, rider
):
    """404 rather than 403, so order ids cannot be mapped by probing."""
    _, headers = customer
    v, vendor_headers = vendor
    order = (await _cash_order(client, headers, v.id, menu_item)).json()
    await _out_for_delivery(client, db, order["id"], vendor_headers, rider)

    other = await client.post(
        "/vendors/me/riders",
        headers=vendor_headers,
        json={"display_name": "Someone Else", "phone": "9876500022"},
    )
    assert other.status_code == 201, other.text
    signed_in = await client.post(
        "/auth/rider/login",
        json={"login_id": other.json()["login_id"], "password": other.json()["password"]},
    )
    stranger = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

    r = await client.post(
        f"/rider/orders/{order['id']}/collect", headers=stranger, json={"method": "cash"}
    )
    assert r.status_code == 404


async def test_collecting_is_refused_on_an_order_paid_online(
    stub_razorpay, signed_webhook, client, customer, vendor, menu_item, rider
):
    """Nothing to collect, and the route must not pretend otherwise."""
    _, headers = customer
    v, vendor_headers = vendor

    placed = await client.post(
        "/orders",
        headers=headers,
        json={
            "vendor_id": str(v.id),
            "items": _lines(menu_item),
            "fulfilment_type": "delivery",
            "delivery_location": "hostel_3",
        },
    )
    order = placed.json()
    session = await client.post(f"/orders/{order['id']}/payment-session", headers=headers)
    await signed_webhook(
        {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_{uuid.uuid4().hex[:14]}",
                        "order_id": session.json()["gateway_order_id"],
                        "status": "captured",
                        "amount": 6000,
                        "currency": "INR",
                    }
                }
            },
        }
    )

    _rider_json, rider_headers = rider
    r = await client.post(
        f"/rider/orders/{order['id']}/collect", headers=rider_headers, json={"method": "cash"}
    )
    assert r.status_code in (400, 404)


# --- the UPI QR -------------------------------------------------------------


async def test_a_upi_qr_is_single_use_and_fixed_to_the_total(
    stub_razorpay, client, db, customer, vendor, menu_item, rider
):
    """What makes it a rider's QR rather than a printed sticker."""
    from decimal import Decimal

    from app.db.models.order import Order
    from app.modules.payments import razorpay

    _, headers = customer
    v, vendor_headers = vendor
    order = (await _cash_order(client, headers, v.id, menu_item)).json()
    rider_headers = await _out_for_delivery(client, db, order["id"], vendor_headers, rider)

    r = await client.post(f"/rider/orders/{order['id']}/upi-qr", headers=rider_headers)
    assert r.status_code == 200, r.text
    assert r.json()["image_url"]

    minted = stub_razorpay["qrs"][-1]
    # total_amount comes back as a JSON string, because money is Numeric and
    # never crosses the wire as a float.
    assert minted["payment_amount"] == razorpay.to_paise(Decimal(order["total_amount"]))
    assert minted["notes"]["order_id"] == order["id"]

    # Stored, because qr_code.credited names only the QR and this is the whole
    # of the mapping back to an order.
    row = await db.get(Order, uuid.UUID(order["id"]))
    await db.refresh(row)
    assert row.cod_qr_id == minted["id"]


async def test_the_qr_webhook_marks_it_paid_without_the_rider_saying_so(
    stub_razorpay, signed_webhook, client, db, customer, vendor, menu_item, rider
):
    """The reason this goes through a gateway at all.

    A stall's own static UPI code would need the rider to assert the money
    arrived. Razorpay says it directly.
    """
    from app.db.models.order import Order

    _, headers = customer
    v, vendor_headers = vendor
    order = (await _cash_order(client, headers, v.id, menu_item)).json()
    rider_headers = await _out_for_delivery(client, db, order["id"], vendor_headers, rider)

    await client.post(f"/rider/orders/{order['id']}/upi-qr", headers=rider_headers)
    qr_id = stub_razorpay["qrs"][-1]["id"]

    r = await signed_webhook(
        {
            "event": "qr_code.credited",
            "payload": {
                "qr_code": {"entity": {"id": qr_id}},
                "payment": {
                    "entity": {
                        "id": f"pay_{uuid.uuid4().hex[:14]}",
                        "status": "captured",
                        "amount": 6000,
                        "currency": "INR",
                    }
                },
            },
        }
    )
    assert r.status_code == 200
    assert r.json()["status"] == "applied"

    row = await db.get(Order, uuid.UUID(order["id"]))
    await db.refresh(row)
    assert row.payment_status.value == "paid"
    assert row.collected_via == "upi"


async def test_a_qr_credit_for_the_wrong_amount_is_not_accepted(
    stub_razorpay, signed_webhook, client, db, customer, vendor, menu_item, rider
):
    """The same check every other payment path gets."""
    from app.db.models.order import Order

    _, headers = customer
    v, vendor_headers = vendor
    order = (await _cash_order(client, headers, v.id, menu_item)).json()
    rider_headers = await _out_for_delivery(client, db, order["id"], vendor_headers, rider)

    await client.post(f"/rider/orders/{order['id']}/upi-qr", headers=rider_headers)
    qr_id = stub_razorpay["qrs"][-1]["id"]

    r = await signed_webhook(
        {
            "event": "qr_code.credited",
            "payload": {
                "qr_code": {"entity": {"id": qr_id}},
                "payment": {"entity": {"id": "pay_short", "status": "captured", "amount": 100}},
            },
        }
    )
    assert r.json()["status"] == "amount_mismatch"

    row = await db.get(Order, uuid.UUID(order["id"]))
    await db.refresh(row)
    assert row.payment_status.value == "due"


async def test_the_rider_is_told_to_take_cash_when_qr_is_not_activated(
    stub_razorpay, client, db, customer, vendor, menu_item, rider, monkeypatch
):
    """QR Codes is activated on request, so a good account can still lack it.

    The rider is standing in front of a customer, so the answer has to be one
    they can act on.
    """
    from app.modules.payments import razorpay

    async def not_enabled(**kwargs):
        raise razorpay.RazorpayError(
            "create_upi_qr failed (400): QR codes are not enabled for this account",
            status_code=400,
            description="QR codes are not enabled for this account",
        )

    monkeypatch.setattr(razorpay, "create_upi_qr", not_enabled)

    _, headers = customer
    v, vendor_headers = vendor
    order = (await _cash_order(client, headers, v.id, menu_item)).json()
    rider_headers = await _out_for_delivery(client, db, order["id"], vendor_headers, rider)

    r = await client.post(f"/rider/orders/{order['id']}/upi-qr", headers=rider_headers)
    assert r.status_code == 503
    assert "cash" in r.json()["detail"].lower()


# --- endings ----------------------------------------------------------------


async def test_cancelling_an_uncollected_order_waives_it_and_refunds_nothing(
    stub_razorpay, client, db, customer, vendor, menu_item
):
    """Nothing was taken, so nothing is owed in either direction.

    And emphatically no gateway refund: there is no payment to reverse, and
    attempting one would be an error line on every cancelled cash order.
    """
    from app.db.models.order import Order

    _, headers = customer
    v, vendor_headers = vendor
    order = (await _cash_order(client, headers, v.id, menu_item)).json()

    r = await client.patch(
        f"/vendors/me/orders/{order['id']}/status",
        headers=vendor_headers,
        json={"status": "rejected"},
    )
    assert r.status_code == 200, r.text

    row = await db.get(Order, uuid.UUID(order["id"]))
    await db.refresh(row)
    assert row.status.value == "rejected"
    assert row.payment_status.value == "waived"
    assert stub_razorpay["refunds"] == []


async def test_a_failed_delivery_can_be_cancelled_at_the_door(
    client, db, customer, vendor, menu_item, rider
):
    """Until pay on delivery there was no ending for this at all.

    out_for_delivery had completion as its only exit, so a customer who refused
    the food left the order stuck forever. The rider reports it; the stall
    decides, which is why RIDER_ALLOWED_TARGETS is unchanged.
    """
    from app.db.models.order import Order

    _, headers = customer
    v, vendor_headers = vendor
    order = (await _cash_order(client, headers, v.id, menu_item)).json()
    rider_headers = await _out_for_delivery(client, db, order["id"], vendor_headers, rider)

    # Not the rider's call.
    refused = await client.patch(
        f"/rider/orders/{order['id']}/status",
        headers=rider_headers,
        json={"status": "cancelled"},
    )
    assert refused.status_code == 403

    r = await client.patch(
        f"/vendors/me/orders/{order['id']}/status",
        headers=vendor_headers,
        json={"status": "cancelled"},
    )
    assert r.status_code == 200, r.text

    row = await db.get(Order, uuid.UUID(order["id"]))
    await db.refresh(row)
    assert row.status.value == "cancelled"
    assert row.payment_status.value == "waived"


async def test_out_for_delivery_to_cancelled_is_allowed_in_the_table():
    """Pinned, because it is a transition added without an ALTER TYPE.

    cancelled already existed and TERMINAL_STATUSES is derived from this dict's
    keys, so the change is one entry - which is exactly the kind of thing a later
    tidy-up removes without noticing.
    """
    from app.db.models.order import OrderStatus
    from app.modules.orders.service import ALLOWED_TRANSITIONS, TERMINAL_STATUSES

    assert OrderStatus.CANCELLED in ALLOWED_TRANSITIONS[OrderStatus.OUT_FOR_DELIVERY]
    assert OrderStatus.COMPLETED in ALLOWED_TRANSITIONS[OrderStatus.OUT_FOR_DELIVERY]
    assert TERMINAL_STATUSES == {
        OrderStatus.COMPLETED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
    }


# --- what the stall is entitled to see --------------------------------------


async def _heard(pubsub, *, seconds: float = 2.0):
    """Read the next real message off a subscription, or None.

    Reads repeatedly rather than once. `ignore_subscribe_messages=True` does not
    skip the subscribe confirmation so much as consume it and hand back None, so
    a single call right after subscribing reliably returns nothing whatever was
    published - which looks exactly like the broadcast being broken.
    """
    import asyncio

    deadline = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < deadline:
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if message is not None:
            return message
    return None


class TestTheStallsQueue:
    """The rule that drifted, and the bug it caused.

    Entitlement used to be written twice: the HTTP list asked "is this past
    awaiting_payment" and the socket broadcast asked "is this paid". The two
    agreed perfectly until cash arrived - a pay-on-delivery order is PLACED and
    still *owed*, so it passed one test and failed the other. It appeared when
    the merchant app refreshed and never arrived live, which also meant the
    new-order alarm never fired for it.

    Both halves are pinned here, because a single predicate can still be
    bypassed by the next person who writes the condition out by hand.
    """

    async def test_a_cash_order_reaches_the_stall_live(
        self, client, db, customer, vendor, menu_item
    ):
        from app.core.redis import get_redis
        from app.modules.orders.service import load_order, publish_order_event, vendor_channel

        redis = get_redis()

        _, headers = customer
        v, _ = vendor

        pubsub = redis.pubsub()
        await pubsub.subscribe(vendor_channel(v.id))
        try:
            order = (await _cash_order(client, headers, v.id, menu_item)).json()
            await publish_order_event(redis, await load_order(uuid.UUID(order["id"]), db))

            assert await _heard(pubsub) is not None, (
                "a cash order never reached the stall's queue live - it is owed, not unpaid"
            )
        finally:
            await pubsub.unsubscribe(vendor_channel(v.id))
            await pubsub.aclose()

    async def test_an_unfinished_checkout_still_does_not(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        """The half that must not have been loosened by fixing the other."""
        from app.core.redis import get_redis
        from app.modules.orders.service import load_order, publish_order_event, vendor_channel

        redis = get_redis()

        _, headers = customer
        v, _ = vendor

        pubsub = redis.pubsub()
        await pubsub.subscribe(vendor_channel(v.id))
        try:
            placed = await client.post(
                "/orders",
                headers=headers,
                json={"vendor_id": str(v.id), "items": _lines(menu_item)},
            )
            assert placed.json()["status"] == "awaiting_payment"
            await publish_order_event(redis, await load_order(uuid.UUID(placed.json()["id"]), db))

            assert await _heard(pubsub, seconds=1.0) is None, (
                "a stall was told about an order nobody has paid for"
            )
        finally:
            await pubsub.unsubscribe(vendor_channel(v.id))
            await pubsub.aclose()

    async def test_the_list_and_the_broadcast_agree(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        """Whatever the socket sends, a refresh must show, and vice versa."""
        from app.db.models.order import Order
        from app.modules.orders.service import stall_may_see

        _, headers = customer
        v, vendor_headers = vendor

        await _cash_order(client, headers, v.id, menu_item)
        await client.post(
            "/orders", headers=headers, json={"vendor_id": str(v.id), "items": _lines(menu_item)}
        )

        listed = await client.get("/vendors/me/orders", headers=vendor_headers)
        assert listed.status_code == 200, listed.text
        listed_ids = {o["id"] for o in listed.json()}

        from sqlalchemy import select

        rows = (
            await db.execute(select(Order).where(Order.vendor_id == v.id))
        ).scalars().all()
        for row in rows:
            assert (str(row.id) in listed_ids) == stall_may_see(row), (
                f"order {row.order_number} ({row.status.value}) disagrees between "
                "the queue and the broadcast rule"
            )
