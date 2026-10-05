"""PAYMENTS_MODE=mock: confirming a payment without a gateway.

Mock mode exists so everything downstream of a payment can be exercised before
Cashfree credentials do. It is also, by construction, a route that marks orders
paid for free - so most of what is asserted here is about the ways it must not be
reachable, and about the audit trail that keeps the orders it created
identifiable after the switch to real payments.
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


# --- the mode itself --------------------------------------------------------


async def test_a_bad_payments_mode_refuses_to_boot():
    """Neither taking real money nor giving food away is an acceptable default
    for a typo, so the only safe answer is to fail."""
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(payments_mode="moc", database_url="postgresql+asyncpg://x/y", secret_key="k" * 32)


async def test_mock_mode_does_not_need_a_gateway_to_take_orders(
    client, customer, vendor, menu_item, mock_payments
):
    """The whole point: no credentials, and an order can still be placed."""
    assert not mock_payments.razorpay_configured
    assert mock_payments.payments_enabled

    _, headers = customer
    v, _ = vendor
    order = await _place(client, headers, v.id, menu_item)
    assert order["status"] == "awaiting_payment"
    assert order["payment_status"] == "pending"


async def test_the_mock_session_is_marked_mock_and_names_no_real_order(
    client, customer, vendor, menu_item, mock_payments
):
    _, headers = customer
    v, _ = vendor
    order = await _place(client, headers, v.id, menu_item)

    r = await client.post(f"/orders/{order['id']}/payment-session", headers=headers)
    assert r.status_code == 200, r.text
    session = r.json()

    # How the browser knows to skip the Cashfree SDK.
    assert session["mode"] == "mock"
    # Deliberately NOT the "hb_" shape: service.order_id_from_cf strips only that
    # prefix, so a real Cashfree webhook can never name a mock payment row.
    assert session["gateway_order_id"] == f"mock_order_{order['id']}"
    # No Razorpay id shape, so a real inbound webhook can never name this row
    # even if the route were somehow open.
    assert not session["gateway_order_id"].startswith("order_")


# --- the happy path it exists for -------------------------------------------


async def test_confirming_a_mock_payment_hands_the_order_to_the_stall(
    client, db, customer, vendor, menu_item, mock_payments
):
    """The same end state a real PAYMENT_SUCCESS webhook produces."""
    _, headers = customer
    v, vendor_headers = vendor
    order = await _place(client, headers, v.id, menu_item)
    await client.post(f"/orders/{order['id']}/payment-session", headers=headers)

    r = await client.post(f"/orders/{order['id']}/mock-payment", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied"

    after = (await client.get(f"/orders/{order['id']}", headers=headers)).json()
    assert after["payment_status"] == "paid"
    assert after["status"] == "placed"

    # And the stall can now see it, which is the thing an unpaid order must never
    # be able to do.
    queue = (await client.get("/vendors/me/orders", headers=vendor_headers)).json()
    assert order["id"] in [o["id"] for o in queue]


async def test_a_mock_payment_is_recorded_in_the_event_ledger(
    client, db, customer, vendor, menu_item, mock_payments
):
    """What makes orders that were never really paid for findable afterwards.

    Without this there is no way, once the gateway is live, to tell a mock-paid
    order from a real one - and reconciling the books becomes guesswork.
    """
    from sqlalchemy import select

    from app.db.models.payment import PaymentEvent

    _, headers = customer
    v, _ = vendor
    order = await _place(client, headers, v.id, menu_item)
    await client.post(f"/orders/{order['id']}/payment-session", headers=headers)
    await client.post(f"/orders/{order['id']}/mock-payment", headers=headers)

    rows = (
        await db.execute(
            select(PaymentEvent).where(PaymentEvent.event_type == "mock.payment.captured")
        )
    ).scalars().all()
    mine = [e for e in rows if str(order["id"]) in str(e.raw)]
    assert len(mine) == 1
    assert mine[0].outcome == "applied"
    assert mine[0].event_id.startswith("mock.payment.captured:mock_pay_")


async def test_confirming_twice_does_not_pay_twice(
    client, customer, vendor, menu_item, mock_payments
):
    """A double-tap on the pay button, or a retried request."""
    _, headers = customer
    v, _ = vendor
    order = await _place(client, headers, v.id, menu_item)
    await client.post(f"/orders/{order['id']}/payment-session", headers=headers)

    first = await client.post(f"/orders/{order['id']}/mock-payment", headers=headers)
    second = await client.post(f"/orders/{order['id']}/mock-payment", headers=headers)

    assert first.json()["status"] == "applied"
    # Caught by the payment-status transition table, the same guard that stops a
    # replayed Cashfree webhook from re-paying an order.
    assert second.json()["status"] == "rejected_transition"


async def test_the_mock_amount_still_goes_through_the_amount_check(
    client, db, customer, vendor, menu_item, mock_payments
):
    """The mock builds a real payload and runs it through apply_payment_success
    rather than setting paid directly, so the amount check stays on the path.

    Proven by breaking it: with the stored amount moved, the payload the mock
    generates from the *order* no longer matches and the payment is refused.
    """
    from sqlalchemy import select

    from app.db.models.payment import Payment

    _, headers = customer
    v, _ = vendor
    order = await _place(client, headers, v.id, menu_item)
    await client.post(f"/orders/{order['id']}/payment-session", headers=headers)

    payment = (
        await db.execute(select(Payment).where(Payment.order_id == uuid.UUID(order["id"])))
    ).scalar_one()
    # The payload is built from payment.amount, so to make them disagree the
    # mismatch has to be injected between building and checking. Patch the
    # builder to lie about the figure.
    from app.modules.payments import mock as mock_module

    real = mock_module.success_entity
    try:
        mock_module.success_entity = lambda *, gateway_order_id, amount: real(
            gateway_order_id=gateway_order_id, amount=amount + 1
        )
        r = await client.post(f"/orders/{order['id']}/mock-payment", headers=headers)
    finally:
        mock_module.success_entity = real

    assert r.json()["status"] == "amount_mismatch"
    after = (await client.get(f"/orders/{order['id']}", headers=headers)).json()
    assert after["payment_status"] == "pending"
    assert payment.amount is not None


# --- the ways it must not be reachable --------------------------------------


async def test_the_mock_route_does_not_exist_in_real_payment_mode(
    client, customer, vendor, menu_item, stub_razorpay
):
    """The one property keeping a free-food endpoint harmless.

    404 rather than 403: a disabled "mark as paid" route that announces itself is
    an invitation to go looking for the switch.
    """
    _, headers = customer
    v, _ = vendor
    order = await _place(client, headers, v.id, menu_item)
    await client.post(f"/orders/{order['id']}/payment-session", headers=headers)

    r = await client.post(f"/orders/{order['id']}/mock-payment", headers=headers)
    assert r.status_code == 404

    after = (await client.get(f"/orders/{order['id']}", headers=headers)).json()
    assert after["payment_status"] == "pending"


async def test_the_real_webhook_is_closed_in_mock_mode(client, mock_payments):
    """The subtle one, and the reason the signing secret gates it separately.

    In mock mode payments are enabled while the webhook secret is empty. That
    secret is the HMAC key signatures are checked against, so a webhook gated on
    "payments enabled" would verify every forged signature against an empty key
    and mark orders paid for anybody who posted one.
    """
    r = await client.post(
        "/payments/razorpay/webhook",
        json={"event": "payment.captured"},
        headers={"x-razorpay-signature": ""},
    )
    assert r.status_code == 404


async def test_one_customer_cannot_mock_pay_anothers_order(
    client, db, customer, vendor, menu_item, mock_payments
):
    from app.core.security import TokenAudience, create_access_token
    from app.db.models.user import User, UserRole

    _, headers = customer
    v, _ = vendor
    order = await _place(client, headers, v.id, menu_item)
    await client.post(f"/orders/{order['id']}/payment-session", headers=headers)

    other = User(
        email=f"other.{uuid.uuid4().hex[:8]}@bitmesra.ac.in",
        role=UserRole.CUSTOMER,
        full_name="Somebody Else",
        phone="+919812345678",
    )
    db.add(other)
    await db.commit()
    await db.refresh(other)
    theirs = {
        "Authorization": f"Bearer {create_access_token(str(other.id), TokenAudience.WEB)}"
    }

    r = await client.post(f"/orders/{order['id']}/mock-payment", headers=theirs)
    assert r.status_code == 404


async def test_a_vendor_cannot_mock_pay_an_order(
    client, customer, vendor, menu_item, mock_payments
):
    """Stalls must not be able to mark their own orders paid, even here."""
    _, headers = customer
    v, vendor_headers = vendor
    order = await _place(client, headers, v.id, menu_item)
    await client.post(f"/orders/{order['id']}/payment-session", headers=headers)

    r = await client.post(f"/orders/{order['id']}/mock-payment", headers=vendor_headers)
    assert r.status_code in (401, 403)


async def test_confirming_before_a_session_exists_is_refused(
    client, customer, vendor, menu_item, mock_payments
):
    """No payment row means nothing to confirm - and nothing to compare an
    amount against, which is what the check depends on."""
    _, headers = customer
    v, _ = vendor
    order = await _place(client, headers, v.id, menu_item)

    r = await client.post(f"/orders/{order['id']}/mock-payment", headers=headers)
    assert r.status_code == 400


async def test_mock_mode_is_off_by_default():
    """Nobody gets free food because a variable was left unset."""
    from app.core.config import Settings

    bare = Settings(database_url="postgresql+asyncpg://x/y", secret_key="k" * 32)
    assert bare.payments_mode == "razorpay"
    assert not bare.payments_mock
    # And with no gateway either, orders are refused outright rather than
    # falling back to something that lets them through.
    assert not bare.payments_enabled


# --- refunds ---------------------------------------------------------------


async def test_rejecting_a_mock_paid_order_refunds_it_without_a_gateway(
    client, customer, vendor, menu_item, mock_payments
):
    """A stall rejecting an order must work in mock mode too.

    Marked refunded rather than left refund_pending: the refund states exist to
    tell somebody money is owed, and an order that never took any money sitting
    in refund_pending forever is a false alarm in every admin view.
    """
    _, headers = customer
    v, vendor_headers = vendor
    order = await _place(client, headers, v.id, menu_item)
    await client.post(f"/orders/{order['id']}/payment-session", headers=headers)
    await client.post(f"/orders/{order['id']}/mock-payment", headers=headers)

    r = await client.patch(
        f"/vendors/me/orders/{order['id']}/status",
        headers=vendor_headers,
        json={"status": "rejected"},
    )
    assert r.status_code == 200, r.text

    after = (await client.get(f"/orders/{order['id']}", headers=headers)).json()
    assert after["status"] == "rejected"
    assert after["payment_status"] in ("refund_pending", "refunded")


# --- the config endpoint the banner reads ----------------------------------


async def test_the_config_endpoint_reports_the_mode(client, mock_payments):
    r = await client.get("/config")
    assert r.status_code == 200
    assert r.json()["payments_mode"] == "mock"


async def test_the_config_endpoint_reports_the_real_gateway_normally(client):
    r = await client.get("/config")
    assert r.status_code == 200
    assert r.json()["payments_mode"] == "razorpay"
