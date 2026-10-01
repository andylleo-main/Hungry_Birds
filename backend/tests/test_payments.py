"""Online payments: who may see an unpaid order, and what a webhook may do.

Two rules carry most of the weight here. A stall must never see an order nobody
has paid for - otherwise somebody can make a kitchen cook for free. And the
webhook is unauthenticated by necessity, so everything it is allowed to change
has to be gated on a signature, an amount, and a transition that is legal.
"""

import uuid

import pytest

pytest.importorskip("httpx")


def _lines(item, qty=1):
    return [{"menu_item_id": str(item.id), "quantity": qty}]


async def _place(client, headers, vendor_id, item, **extra):
    r = await client.post(
        "/orders",
        headers=headers,
        json={"vendor_id": str(vendor_id), "items": _lines(item), **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _checkout(client, headers, vendor_id, item, **extra):
    """Place an order and open its payment session, as the web app does.

    A webhook only means anything for an order somebody actually started paying
    for, so tests that send one go through this rather than inserting a payments
    row behind the endpoint's back.
    """
    order = await _place(client, headers, vendor_id, item, **extra)
    session = await client.post(f"/orders/{order['id']}/payment-session", headers=headers)
    assert session.status_code == 200, session.text
    assert session.json()["cf_order_id"] == f"hb_{order['id']}"
    # No amount is handed to the browser - there is nothing there to tamper with.
    assert "amount" not in session.json()
    return order


def _success_body(order_id, amount="60.00", cf_payment_id=None):
    """The shape Cashfree actually posts on a successful payment.

    The payment id is random per call because it is what the idempotency ledger
    keys on, and that ledger is a durable table - a fixed id would make every run
    after the first see its own events as replays.
    """
    cf_payment_id = cf_payment_id or str(uuid.uuid4().int % 10**12)
    return {
        "type": "PAYMENT_SUCCESS_WEBHOOK",
        "data": {
            "order": {
                "order_id": f"hb_{order_id}",
                "order_amount": float(amount),
                "order_currency": "INR",
            },
            "payment": {
                "cf_payment_id": cf_payment_id,
                "payment_status": "SUCCESS",
                "payment_amount": float(amount),
            },
        },
    }


# --- an unpaid order belongs to nobody but its customer ---------------------


async def test_a_new_order_is_unpaid_and_invisible_to_the_stall(
    client, customer, vendor, menu_item
):
    user, cust_headers = customer
    v, vendor_headers = vendor

    order = await _place(client, cust_headers, v.id, menu_item)
    assert order["status"] == "awaiting_payment"
    assert order["payment_status"] == "pending"

    # Not in the queue...
    queue = await client.get("/vendors/me/orders", headers=vendor_headers)
    assert order["id"] not in [o["id"] for o in queue.json()]

    # ...and not reachable by id either, so guessing one buys nothing.
    direct = await client.get(f"/orders/{order['id']}", headers=vendor_headers)
    assert direct.status_code == 404

    # The customer still sees their own, so the page can tell them to pay.
    mine = await client.get(f"/orders/{order['id']}", headers=cust_headers)
    assert mine.status_code == 200
    assert mine.json()["status"] == "awaiting_payment"


async def test_an_unpaid_order_is_never_broadcast_to_the_stalls_queue(
    client, db, customer, vendor, menu_item
):
    """The socket half of the same rule.

    Subscribes to the stall's channel for real, places an unpaid order, then pays
    it - and asserts the stall hears exactly one thing: the paid one.
    """
    from app.core.redis import get_redis
    from app.db.models.order import Order, OrderStatus
    from app.db.models.payment import PaymentStatus
    from app.modules.orders.service import load_order, publish_order_event, vendor_channel

    user, cust_headers = customer
    v, _ = vendor

    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(vendor_channel(v.id))
    try:
        order = await _place(client, cust_headers, v.id, menu_item)

        # Nothing on the stall's channel for an unpaid order.
        assert await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5) is None

        row = await db.get(Order, uuid.UUID(order["id"]))
        row.payment_status = PaymentStatus.PAID
        row.status = OrderStatus.PLACED
        await db.commit()

        await publish_order_event(redis, await load_order(uuid.UUID(order["id"]), db))
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)
        assert message is not None, "a paid order should reach the stall"
    finally:
        await pubsub.unsubscribe(vendor_channel(v.id))
        await pubsub.aclose()


# --- the webhook ------------------------------------------------------------


async def test_an_unsigned_webhook_is_refused(client, payments_on):
    r = await client.post(
        "/payments/cashfree/webhook",
        content=b'{"type":"PAYMENT_SUCCESS_WEBHOOK"}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 401


async def test_a_tampered_webhook_is_refused(stub_cashfree, signed_webhook, customer, vendor, menu_item, client):
    user, cust_headers = customer
    v, _ = vendor
    order = await _checkout(client, cust_headers, v.id, menu_item)

    r = await signed_webhook(_success_body(order["id"]), signature="not-the-right-signature")
    assert r.status_code == 401


async def test_a_replayed_webhook_is_refused_once_it_is_stale(
    stub_cashfree, signed_webhook, customer, vendor, menu_item, client
):
    """A captured body with a valid signature must not work forever."""
    import time

    user, cust_headers = customer
    v, _ = vendor
    order = await _place(client, cust_headers, v.id, menu_item)

    old = str(int(time.time()) - 3600)
    r = await signed_webhook(_success_body(order["id"]), timestamp=old)
    assert r.status_code == 401


async def test_a_successful_payment_hands_the_order_to_the_stall(
    stub_cashfree, signed_webhook, client, customer, vendor, menu_item
):
    user, cust_headers = customer
    v, vendor_headers = vendor
    order = await _checkout(client, cust_headers, v.id, menu_item)

    r = await signed_webhook(_success_body(order["id"]))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied"

    fresh = await client.get(f"/orders/{order['id']}", headers=cust_headers)
    assert fresh.json()["status"] == "placed"
    assert fresh.json()["payment_status"] == "paid"

    # And now, and only now, the stall has it.
    queue = await client.get("/vendors/me/orders", headers=vendor_headers)
    assert order["id"] in [o["id"] for o in queue.json()]


async def test_the_same_webhook_twice_changes_nothing_the_second_time(
    stub_cashfree, signed_webhook, client, customer, vendor, menu_item
):
    """Cashfree retries anything it does not get a 2xx for."""
    user, cust_headers = customer
    v, _ = vendor
    order = await _checkout(client, cust_headers, v.id, menu_item)
    body = _success_body(order["id"])

    first = await signed_webhook(body)
    assert first.json()["status"] == "applied"

    second = await signed_webhook(body)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"


async def test_a_payment_for_the_wrong_amount_is_not_accepted(
    stub_cashfree, signed_webhook, client, db, customer, vendor, menu_item
):
    """The one check standing between us and a forged amount."""
    from app.db.models.order import Order

    user, cust_headers = customer
    v, _ = vendor
    order = await _checkout(client, cust_headers, v.id, menu_item)  # priced at 60.00

    r = await signed_webhook(_success_body(order["id"], amount="1.00"))
    assert r.status_code == 200
    assert r.json()["status"] == "amount_mismatch"

    row = await db.get(Order, uuid.UUID(order["id"]))
    await db.refresh(row)
    assert row.payment_status.value == "pending"
    assert row.status.value == "awaiting_payment"


async def test_a_late_failure_cannot_unpay_a_paid_order(
    stub_cashfree, signed_webhook, client, db, customer, vendor, menu_item
):
    """Cashfree does not promise an order, so this has to be designed for."""
    from app.db.models.order import Order

    user, cust_headers = customer
    v, _ = vendor
    order = await _checkout(client, cust_headers, v.id, menu_item)

    assert (await signed_webhook(_success_body(order["id"]))).json()["status"] == "applied"

    failed = {
        "type": "PAYMENT_FAILED_WEBHOOK",
        "data": {
            "order": {"order_id": f"hb_{order['id']}", "order_amount": 60.0},
            "payment": {
                "cf_payment_id": str(uuid.uuid4().int % 10**12),
                "payment_status": "FAILED",
            },
        },
    }
    r = await signed_webhook(failed)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected_transition"

    row = await db.get(Order, uuid.UUID(order["id"]))
    await db.refresh(row)
    assert row.payment_status.value == "paid"


async def test_a_webhook_for_an_order_we_do_not_have_is_shrugged_off(
    signed_webhook
):
    """200, not 500 - a retry cannot make an unknown order exist."""
    r = await signed_webhook(_success_body(uuid.uuid4()))
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


async def test_the_webhook_does_not_exist_until_cashfree_is_configured(client, payments_off):
    """Nothing can be verified, so the route must not accept anything."""
    r = await client.post(
        "/payments/cashfree/webhook",
        content=b"{}",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 404


# --- refunds ----------------------------------------------------------------


async def test_rejecting_a_paid_order_starts_a_refund(
    stub_cashfree, signed_webhook, client, db, customer, vendor, menu_item
):
    from app.db.models.order import Order

    user, cust_headers = customer
    v, vendor_headers = vendor
    order = await _checkout(client, cust_headers, v.id, menu_item)
    await signed_webhook(_success_body(order["id"]))

    r = await client.patch(
        f"/vendors/me/orders/{order['id']}/status",
        headers=vendor_headers,
        json={"status": "rejected"},
    )
    assert r.status_code == 200, r.text

    row = await db.get(Order, uuid.UUID(order["id"]))
    await db.refresh(row)
    assert row.status.value == "rejected"
    assert row.payment_status.value == "refund_pending"


async def test_a_stall_can_still_reject_while_cashfree_is_down(
    stub_cashfree, signed_webhook, client, db, customer, vendor, menu_item, monkeypatch
):
    """The property the whole refund design exists to protect.

    A stall that has run out of something must be able to say so, whatever is
    happening at the payment provider.
    """
    from app.db.models.order import Order
    from app.modules.payments import cashfree

    async def explode(**kwargs):
        raise cashfree.CashfreeError("gateway down")

    monkeypatch.setattr(cashfree, "refund", explode)

    user, cust_headers = customer
    v, vendor_headers = vendor
    order = await _checkout(client, cust_headers, v.id, menu_item)
    await signed_webhook(_success_body(order["id"]))

    r = await client.patch(
        f"/vendors/me/orders/{order['id']}/status",
        headers=vendor_headers,
        json={"status": "rejected"},
    )
    assert r.status_code == 200, r.text

    # Still owed, and still marked as owed, so a later drain can retry.
    row = await db.get(Order, uuid.UUID(order["id"]))
    await db.refresh(row)
    assert row.payment_status.value == "refund_pending"


# --- abandoned checkouts ----------------------------------------------------


async def test_an_abandoned_checkout_is_written_off_eventually(
    client, db, customer, vendor, menu_item, payments_on
):
    """No scheduler exists, so the sweep rides on the read that would show it."""
    from datetime import datetime, timedelta, timezone

    from app.db.models.order import Order

    user, cust_headers = customer
    v, _ = vendor
    order = await _place(client, cust_headers, v.id, menu_item)

    # Older than Cashfree's own expiry plus the local grace period.
    row = await db.get(Order, uuid.UUID(order["id"]))
    row.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await db.commit()

    listed = await client.get("/orders", headers=cust_headers)
    assert listed.status_code == 200
    mine = next(o for o in listed.json() if o["id"] == order["id"])
    assert mine["status"] == "cancelled"
    assert mine["payment_status"] == "expired"


async def test_the_sweep_leaves_a_paid_order_alone(
    stub_cashfree, signed_webhook, client, db, customer, vendor, menu_item
):
    """The predicate is load-bearing: a sweep must never touch real money."""
    from datetime import datetime, timedelta, timezone

    from app.db.models.order import Order

    user, cust_headers = customer
    v, _ = vendor
    order = await _checkout(client, cust_headers, v.id, menu_item)
    await signed_webhook(_success_body(order["id"]))

    row = await db.get(Order, uuid.UUID(order["id"]))
    row.created_at = datetime.now(timezone.utc) - timedelta(days=3)
    await db.commit()

    listed = await client.get("/orders", headers=cust_headers)
    mine = next(o for o in listed.json() if o["id"] == order["id"])
    assert mine["status"] == "placed"
    assert mine["payment_status"] == "paid"


# --- configuration ----------------------------------------------------------


async def test_no_orders_are_taken_until_cashfree_is_configured(
    client, customer, vendor, menu_item, payments_off
):
    """Refused up front, rather than accepted and left unfinishable.

    Payment is the only route out of awaiting_payment, so an order created
    without a gateway would sit forever - the customer holding a confirmation
    for food no stall will ever see, and nothing anywhere explaining why.
    """
    user, cust_headers = customer
    v, _ = vendor

    r = await client.post(
        "/orders",
        headers=cust_headers,
        json={"vendor_id": str(v.id), "items": _lines(menu_item)},
    )
    assert r.status_code == 503
    assert "payments are not set up" in r.json()["detail"].lower()


async def test_one_customer_cannot_open_anothers_checkout(
    client, db, customer, vendor, menu_item, payments_on
):
    from app.core.security import TokenAudience, create_access_token
    from app.db.models.user import User, UserRole

    user, cust_headers = customer
    v, _ = vendor
    order = await _place(client, cust_headers, v.id, menu_item)

    intruder = User(
        email=f"nosy.{uuid.uuid4().hex[:8]}@bitmesra.ac.in",
        role=UserRole.CUSTOMER,
        phone="+919812300000",
    )
    db.add(intruder)
    await db.commit()
    await db.refresh(intruder)
    headers = {
        "Authorization": f"Bearer {create_access_token(str(intruder.id), TokenAudience.WEB)}"
    }

    r = await client.post(f"/orders/{order['id']}/payment-session", headers=headers)
    assert r.status_code == 404


async def test_payment_status_reads_back_as_an_enum_not_a_string(
    client, db, customer, vendor, menu_item
):
    """Guards a bug that fails completely silently.

    The column is VARCHAR. Mapped as a bare String it reads back as `str`, and
    every `order.payment_status is PaymentStatus.PAID` in the codebase becomes
    permanently False - so refunds never start, and nothing raises to say so.
    Equality would still work, which is what makes it survive review.
    """
    from sqlalchemy import text

    from app.db.models.order import Order
    from app.db.models.payment import PaymentStatus

    user, cust_headers = customer
    v, _ = vendor
    order = await _place(client, cust_headers, v.id, menu_item)

    row = await db.get(Order, uuid.UUID(order["id"]))
    assert isinstance(row.payment_status, PaymentStatus)
    assert row.payment_status is PaymentStatus.PENDING

    # And the value that reaches Postgres is the member's value, not its name.
    stored = await db.execute(
        text("SELECT payment_status FROM orders WHERE id = :i"), {"i": str(row.id)}
    )
    assert stored.scalar_one() == "pending"
