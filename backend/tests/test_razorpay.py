"""What changed when the gateway did.

Cashfree and Razorpay differ in four ways that each removed a guarantee the old
code leaned on. This file is one section per removed guarantee, because those are
the places a bug would be about money rather than about plumbing:

- Razorpay mints the order id, so a webhook is matched by query rather than by
  parsing a prefix we chose.
- Razorpay mints the refund id, so a retry is no longer idempotent for free.
- Razorpay sends no webhook timestamp, so a stale replay cannot be rejected by
  age.
- The webhook signing secret is a different value from the API key secret.
"""

import uuid
from decimal import Decimal

import pytest

pytest.importorskip("httpx")


def _lines(item, qty=1):
    return [{"menu_item_id": str(item.id), "quantity": qty}]


async def _checkout(client, headers, vendor_id, item):
    r = await client.post(
        "/orders", headers=headers, json={"vendor_id": str(vendor_id), "items": _lines(item)}
    )
    assert r.status_code == 201, r.text
    order = r.json()
    session = await client.post(f"/orders/{order['id']}/payment-session", headers=headers)
    assert session.status_code == 200, session.text
    return order, session.json()


def _captured(gateway_order_id, amount="60.00", payment_id=None):
    return {
        "id": payment_id or f"pay_{uuid.uuid4().hex[:14]}",
        "entity": "payment",
        "order_id": str(gateway_order_id),
        "status": "captured",
        "amount": int(round(float(amount) * 100)),
        "currency": "INR",
    }


# --- money arithmetic -------------------------------------------------------


def test_rupees_become_whole_paise():
    """Every amount Razorpay states is an integer of paise.

    The quantize in to_paise is not decoration: 19.99 * 100 is 1998.9999... in
    binary floating point, and a truncating conversion would charge a paisa less
    than the stall was told - after which the webhook's own amount check would
    reject the customer's payment.
    """
    from app.modules.payments.razorpay import from_paise, to_paise

    assert to_paise(Decimal("60.00")) == 6000
    assert to_paise(Decimal("19.99")) == 1999
    assert to_paise(Decimal("0.01")) == 1
    assert to_paise(Decimal("1250.50")) == 125050
    assert from_paise(125050) == Decimal("1250.50")


# --- the two signatures, which are easy to confuse --------------------------


def test_the_webhook_and_checkout_signatures_use_different_secrets():
    """Both are HMAC-SHA256 and they are keyed differently on purpose.

    Swapping them fails closed in both directions - every real webhook rejected,
    or every real payment rejected - so the failure is loud. What would not be
    loud is a future refactor collapsing the two settings into one, which this
    pins against.
    """
    import hashlib
    import hmac

    from app.core.config import get_settings
    from app.modules.payments import razorpay

    settings = get_settings().model_copy(
        update={
            "razorpay_key_secret": "the-api-secret",
            "razorpay_webhook_secret": "the-webhook-secret",
        }
    )

    body = b'{"event":"payment.captured"}'
    by_webhook_secret = hmac.new(b"the-webhook-secret", body, hashlib.sha256).hexdigest()
    by_api_secret = hmac.new(b"the-api-secret", body, hashlib.sha256).hexdigest()

    assert razorpay.verify_webhook(
        raw_body=body, signature=by_webhook_secret, settings=settings
    )
    assert not razorpay.verify_webhook(
        raw_body=body, signature=by_api_secret, settings=settings
    )

    handback = hmac.new(b"the-api-secret", b"order_X|pay_Y", hashlib.sha256).hexdigest()
    assert razorpay.verify_checkout_signature(
        gateway_order_id="order_X", payment_id="pay_Y", signature=handback, settings=settings
    )
    assert not razorpay.verify_checkout_signature(
        gateway_order_id="order_X",
        payment_id="pay_Y",
        signature=hmac.new(b"the-webhook-secret", b"order_X|pay_Y", hashlib.sha256).hexdigest(),
        settings=settings,
    )


def test_an_empty_secret_verifies_nothing():
    """An unconfigured deployment must not accept the empty-key signature."""
    import hashlib
    import hmac

    from app.core.config import get_settings
    from app.modules.payments import razorpay

    settings = get_settings().model_copy(update={"razorpay_webhook_secret": ""})
    forged = hmac.new(b"", b"{}", hashlib.sha256).hexdigest()
    assert not razorpay.verify_webhook(raw_body=b"{}", signature=forged, settings=settings)


# --- refunds: the guarantee Razorpay took away ------------------------------


class TestRefundsAreNotPaidTwice:
    """The riskiest change in the gateway swap.

    Cashfree accepted a refund id we chose and was idempotent on it, so the retry
    drain could re-drive a refund as often as it liked. Razorpay mints its own,
    so the same drain would create a second refund and send a customer their
    money twice. Two guards replace it, and both are tested here.
    """

    async def test_an_existing_refund_is_adopted_rather_than_repeated(
        self, stub_razorpay, client, db, customer, vendor, menu_item, payments_on
    ):
        """Guard 2: an attempt that got through and then died is not repeated.

        Standing in for the real failure - the process dying between Razorpay
        accepting a refund and us recording its id - by telling list_refunds that
        one already exists. Nothing new may be created.
        """
        from app.db.models.order import Order, OrderStatus
        from app.db.models.payment import Payment, PaymentStatus
        from app.modules.payments import service

        _, headers = customer
        v, _ = vendor
        order, _session = await _checkout(client, headers, v.id, menu_item)
        order_id = uuid.UUID(order["id"])

        row = await db.get(Order, order_id)
        row.status = OrderStatus.REJECTED
        row.payment_status = PaymentStatus.PAID
        payment = (
            await db.execute(select_payment(order_id))
        ).scalar_one()
        payment.gateway_payment_id = "pay_alreadytried"
        await db.commit()

        await service.start_refund(order_id, "stall said no", db)

        stub_razorpay["existing_refunds"] = [{"id": "rfnd_fromtheearlierattempt"}]
        await service.attempt_refund(order_id, "retrying an unfinished refund", payments_on)

        assert stub_razorpay["refunds"] == [], "a second refund was created for the same payment"

        await db.refresh(payment)
        assert payment.refund_id == "rfnd_fromtheearlierattempt"

    async def test_a_first_refund_is_created_normally(
        self, stub_razorpay, client, db, customer, vendor, menu_item, payments_on
    ):
        """The other half: with nothing open, one refund is made and recorded."""
        from app.db.models.order import Order, OrderStatus
        from app.db.models.payment import PaymentStatus
        from app.modules.payments import service

        _, headers = customer
        v, _ = vendor
        order, _session = await _checkout(client, headers, v.id, menu_item)
        order_id = uuid.UUID(order["id"])

        row = await db.get(Order, order_id)
        row.status = OrderStatus.REJECTED
        row.payment_status = PaymentStatus.PAID
        payment = (await db.execute(select_payment(order_id))).scalar_one()
        payment.gateway_payment_id = "pay_thecustomerspayment"
        await db.commit()

        await service.start_refund(order_id, "stall said no", db)
        await service.attempt_refund(order_id, "stall said no", payments_on)

        assert len(stub_razorpay["refunds"]) == 1
        assert stub_razorpay["refunds"][0]["payment_id"] == "pay_thecustomerspayment"
        assert stub_razorpay["refunds"][0]["amount"] == Decimal("60.00")

        await db.refresh(payment)
        assert payment.refund_id.startswith("rfnd_")

    async def test_two_drains_racing_only_refund_once(
        self, stub_razorpay, client, db, customer, vendor, menu_item, payments_on
    ):
        """Guard 1: the compare-and-set claim on the attempt counter.

        There is no distributed lock, and two reads of the same customer's order
        list can pick the same stuck refund. Both call attempt_refund; only one
        may reach the gateway.
        """
        import asyncio

        from app.db.models.order import Order, OrderStatus
        from app.db.models.payment import PaymentStatus
        from app.modules.payments import service

        _, headers = customer
        v, _ = vendor
        order, _session = await _checkout(client, headers, v.id, menu_item)
        order_id = uuid.UUID(order["id"])

        row = await db.get(Order, order_id)
        row.status = OrderStatus.REJECTED
        row.payment_status = PaymentStatus.PAID
        payment = (await db.execute(select_payment(order_id))).scalar_one()
        payment.gateway_payment_id = "pay_contended"
        await db.commit()

        await service.start_refund(order_id, "stall said no", db)

        await asyncio.gather(
            service.attempt_refund(order_id, "drain a", payments_on),
            service.attempt_refund(order_id, "drain b", payments_on),
            return_exceptions=True,
        )

        assert len(stub_razorpay["refunds"]) == 1, (
            f"{len(stub_razorpay['refunds'])} refunds were created for one order"
        )

    async def test_a_refund_with_no_recorded_payment_id_finds_it_at_the_gateway(
        self, stub_razorpay, client, db, customer, vendor, menu_item, payments_on, monkeypatch
    ):
        """A refund is due but no webhook ever landed, so we hold no payment id.

        Razorpay still knows which payments were made against the order. Without
        this the refund is simply impossible and a customer waits on a human.
        """
        from app.db.models.order import Order, OrderStatus
        from app.db.models.payment import PaymentStatus
        from app.modules.payments import razorpay, service

        _, headers = customer
        v, _ = vendor
        order, session = await _checkout(client, headers, v.id, menu_item)
        order_id = uuid.UUID(order["id"])

        async def one_captured_payment(gateway_order_id, settings):
            return [
                {"id": "pay_failed_attempt", "status": "failed"},
                {"id": "pay_thegoodone", "status": "captured"},
            ]

        monkeypatch.setattr(razorpay, "order_payments", one_captured_payment)

        row = await db.get(Order, order_id)
        row.status = OrderStatus.CANCELLED
        row.payment_status = PaymentStatus.PAID
        await db.commit()

        await service.start_refund(order_id, "stall cancelled", db)
        await service.attempt_refund(order_id, "stall cancelled", payments_on)

        assert len(stub_razorpay["refunds"]) == 1
        assert stub_razorpay["refunds"][0]["payment_id"] == "pay_thegoodone"


def select_payment(order_id):
    from sqlalchemy import select

    from app.db.models.payment import Payment

    return select(Payment).where(Payment.order_id == order_id)


# --- the checkout callback --------------------------------------------------


class TestTheCheckoutCallback:
    """The insurance against a misconfigured webhook.

    It is a second door to "paid", so it is held to the same standard as the
    first: the signature proves Razorpay issued the payment for this order, and
    the amount and capture state are read from the API rather than from a page
    the customer can edit.
    """

    @staticmethod
    def _handback(settings, gateway_order_id, payment_id):
        import hashlib
        import hmac

        return hmac.new(
            settings.razorpay_key_secret.encode(),
            f"{gateway_order_id}|{payment_id}".encode(),
            hashlib.sha256,
        ).hexdigest()

    async def test_a_signed_handback_marks_the_order_paid(
        self, stub_razorpay, client, db, customer, vendor, menu_item, payments_on, monkeypatch
    ):
        from app.db.models.order import Order
        from app.modules.payments import razorpay

        _, headers = customer
        v, _ = vendor
        order, session = await _checkout(client, headers, v.id, menu_item)
        gw = session["gateway_order_id"]

        async def fake_fetch(payment_id, settings):
            return _captured(gw, payment_id=payment_id)

        monkeypatch.setattr(razorpay, "fetch_payment", fake_fetch)

        # Unique per run: the callback keys the ledger on "checkout:{payment_id}"
        # and that table is durable, so a literal id would make the second run
        # see its own event as a replay.
        pay = f"pay_{uuid.uuid4().hex[:14]}"
        r = await client.post(
            f"/orders/{order['id']}/payment-callback",
            headers=headers,
            json={
                "razorpay_order_id": gw,
                "razorpay_payment_id": pay,
                "razorpay_signature": self._handback(payments_on, gw, pay),
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "applied"

        row = await db.get(Order, uuid.UUID(order["id"]))
        await db.refresh(row)
        assert row.payment_status.value == "paid"
        # The stall can see it, and it has a token to call out.
        assert row.status.value == "placed"
        assert row.token_number is not None

    async def test_a_forged_signature_is_refused(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        from app.db.models.order import Order

        _, headers = customer
        v, _ = vendor
        order, session = await _checkout(client, headers, v.id, menu_item)

        r = await client.post(
            f"/orders/{order['id']}/payment-callback",
            headers=headers,
            json={
                "razorpay_order_id": session["gateway_order_id"],
                "razorpay_payment_id": "pay_madeup",
                "razorpay_signature": "nothing-like-a-signature",
            },
        )
        assert r.status_code == 401

        row = await db.get(Order, uuid.UUID(order["id"]))
        await db.refresh(row)
        assert row.payment_status.value == "pending"

    async def test_a_payment_signed_for_another_order_is_refused(
        self, stub_razorpay, client, db, customer, vendor, menu_item, payments_on
    ):
        """Why the order id is inside the signed string.

        A perfectly valid handback for one order, replayed against another, must
        not pay for the second one.
        """
        from app.db.models.order import Order

        _, headers = customer
        v, _ = vendor
        first, first_session = await _checkout(client, headers, v.id, menu_item)
        second, _second_session = await _checkout(client, headers, v.id, menu_item)

        gw = first_session["gateway_order_id"]
        r = await client.post(
            f"/orders/{second['id']}/payment-callback",
            headers=headers,
            json={
                "razorpay_order_id": gw,
                "razorpay_payment_id": "pay_forthefirstorder",
                "razorpay_signature": self._handback(payments_on, gw, "pay_forthefirstorder"),
            },
        )
        assert r.status_code == 400

        row = await db.get(Order, uuid.UUID(second["id"]))
        await db.refresh(row)
        assert row.payment_status.value == "pending"

    async def test_an_amount_the_gateway_disagrees_with_is_not_accepted(
        self, stub_razorpay, client, db, customer, vendor, menu_item, payments_on, monkeypatch
    ):
        """The reason the amount is read from Razorpay and not from the page."""
        from app.db.models.order import Order
        from app.modules.payments import razorpay

        _, headers = customer
        v, _ = vendor
        order, session = await _checkout(client, headers, v.id, menu_item)
        gw = session["gateway_order_id"]

        async def underpaid(payment_id, settings):
            return _captured(gw, amount="1.00", payment_id=payment_id)

        monkeypatch.setattr(razorpay, "fetch_payment", underpaid)

        pay = f"pay_{uuid.uuid4().hex[:14]}"
        r = await client.post(
            f"/orders/{order['id']}/payment-callback",
            headers=headers,
            json={
                "razorpay_order_id": gw,
                "razorpay_payment_id": pay,
                "razorpay_signature": self._handback(payments_on, gw, pay),
            },
        )
        assert r.json()["status"] == "amount_mismatch"

        row = await db.get(Order, uuid.UUID(order["id"]))
        await db.refresh(row)
        assert row.payment_status.value == "pending"

    async def test_an_authorised_but_uncaptured_payment_is_not_paid(
        self, stub_razorpay, client, db, customer, vendor, menu_item, payments_on, monkeypatch
    ):
        """Nothing is marked paid on a maybe. The webhook will say when it settles."""
        from app.db.models.order import Order
        from app.modules.payments import razorpay

        _, headers = customer
        v, _ = vendor
        order, session = await _checkout(client, headers, v.id, menu_item)
        gw = session["gateway_order_id"]

        async def only_authorised(payment_id, settings):
            entity = _captured(gw, payment_id=payment_id)
            entity["status"] = "authorized"
            return entity

        monkeypatch.setattr(razorpay, "fetch_payment", only_authorised)

        r = await client.post(
            f"/orders/{order['id']}/payment-callback",
            headers=headers,
            json={
                "razorpay_order_id": gw,
                "razorpay_payment_id": "pay_notcaptured",
                "razorpay_signature": self._handback(payments_on, gw, "pay_notcaptured"),
            },
        )
        assert r.json()["status"] == "ignored"

        row = await db.get(Order, uuid.UUID(order["id"]))
        await db.refresh(row)
        assert row.payment_status.value == "pending"

    async def test_the_webhook_arriving_afterwards_changes_nothing(
        self,
        stub_razorpay,
        signed_webhook,
        client,
        db,
        customer,
        vendor,
        menu_item,
        payments_on,
        monkeypatch,
    ):
        """Both doors, in the order they really happen. The second is a no-op.

        This is what makes the callback safe to have at all: it writes the same
        ledger and goes through the same transition guard, so the webhook that
        follows records itself and changes nothing.
        """
        from app.db.models.order import Order
        from app.modules.payments import razorpay

        _, headers = customer
        v, _ = vendor
        order, session = await _checkout(client, headers, v.id, menu_item)
        gw = session["gateway_order_id"]

        async def fake_fetch(payment_id, settings):
            return _captured(gw, payment_id=payment_id)

        monkeypatch.setattr(razorpay, "fetch_payment", fake_fetch)

        pay = f"pay_{uuid.uuid4().hex[:14]}"
        callback = await client.post(
            f"/orders/{order['id']}/payment-callback",
            headers=headers,
            json={
                "razorpay_order_id": gw,
                "razorpay_payment_id": pay,
                "razorpay_signature": self._handback(payments_on, gw, pay),
            },
        )
        assert callback.json()["status"] == "applied"

        late = await signed_webhook(
            {
                "event": "payment.captured",
                "payload": {"payment": {"entity": _captured(gw, payment_id=pay)}},
            }
        )
        assert late.status_code == 200
        assert late.json()["status"] == "rejected_transition"

        row = await db.get(Order, uuid.UUID(order["id"]))
        await db.refresh(row)
        assert row.payment_status.value == "paid"
        assert row.token_number is not None


# --- events we deliberately do not act on -----------------------------------


async def test_order_paid_is_ignored_in_favour_of_payment_captured(
    stub_razorpay, signed_webhook, client, db, customer, vendor, menu_item
):
    """Razorpay describes one payment with several events.

    order.paid and payment.authorized both describe something payment.captured
    describes again. Acting on more than one is two paths to the same transition
    and two chances to disagree about it.
    """
    from app.db.models.order import Order

    _, headers = customer
    v, _ = vendor
    order, session = await _checkout(client, headers, v.id, menu_item)
    gw = session["gateway_order_id"]

    r = await signed_webhook(
        {
            "event": "order.paid",
            "payload": {"payment": {"entity": _captured(gw)}},
        }
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"

    row = await db.get(Order, uuid.UUID(order["id"]))
    await db.refresh(row)
    assert row.payment_status.value == "pending"
    assert row.status.value == "awaiting_payment"


async def test_a_refund_webhook_without_a_payment_entity_still_finds_its_order(
    stub_razorpay, signed_webhook, client, db, customer, vendor, menu_item
):
    """Some refund events carry only the refund.

    The refund names the payment it reverses, and we recorded that id when the
    payment landed, so the order is still reachable.
    """
    from app.db.models.order import Order, OrderStatus
    from app.db.models.payment import PaymentStatus

    _, headers = customer
    v, _ = vendor
    order, session = await _checkout(client, headers, v.id, menu_item)
    order_id = uuid.UUID(order["id"])

    payment = (await db.execute(select_payment(order_id))).scalar_one()
    # Unique per run: the refund webhook finds its order by querying this column,
    # and rows from earlier runs survive in the database.
    pay = f"pay_{uuid.uuid4().hex[:14]}"
    payment.gateway_payment_id = pay
    row = await db.get(Order, order_id)
    row.status = OrderStatus.REJECTED
    row.payment_status = PaymentStatus.REFUND_PENDING
    await db.commit()

    r = await signed_webhook(
        {
            "event": "refund.processed",
            "payload": {
                "refund": {
                    "entity": {
                        "id": f"rfnd_{uuid.uuid4().hex[:14]}",
                        "payment_id": pay,
                        "status": "processed",
                        "amount": 6000,
                    }
                }
            },
        }
    )
    assert r.status_code == 200
    assert r.json()["status"] == "applied"

    await db.refresh(row)
    assert row.payment_status.value == "refunded"
