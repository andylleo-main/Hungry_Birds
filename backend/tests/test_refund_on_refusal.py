"""Money goes back whenever a stall ends an order without feeding anybody.

The vendor status route refunded on `rejected` and nothing else, while the
transition table has always allowed `cancelled` from both `placed` and
`accepted`. A stall that sent cancelled on a paid order therefore closed it and
kept the money - silently, with nothing in any log, and with the customer's
tracking page showing a cancelled order and no refund.

So the condition is derived from the transition table rather than written as a
list of statuses, and these tests pin the derivation as much as the behaviour:
if somebody adds a terminal status later, the money has to follow it without
anybody remembering to come back here.
"""

import uuid

import pytest

pytest.importorskip("httpx")


def _lines(item, qty=1):
    return [{"menu_item_id": str(item.id), "quantity": qty}]


def _success_body(order_id, amount="60.00"):
    """The shape Cashfree posts on a successful payment.

    Same as the copy in test_payments.py, and random per call for the same
    reason: the payment id is what the idempotency ledger keys on, and that
    ledger is a durable table, so a fixed id makes every run after the first see
    its own events as replays.
    """
    return {
        "type": "PAYMENT_SUCCESS_WEBHOOK",
        "data": {
            "order": {
                "order_id": f"hb_{order_id}",
                "order_amount": float(amount),
                "order_currency": "INR",
            },
            "payment": {
                "cf_payment_id": str(uuid.uuid4().int % 10**12),
                "payment_status": "SUCCESS",
                "payment_amount": float(amount),
            },
        },
    }


async def _paid_order(client, headers, vendor_id, item, signed_webhook):
    """An order paid for the way a real one is: session opened, webhook landed.

    Deliberately not a hand-written payment_status. A refund needs the payments
    row that opening the session creates, and flipping the column by hand
    produces an order that looks paid and has no gateway behind it - which
    start_refund now correctly refuses to act on.
    """
    r = await client.post(
        "/orders",
        headers=headers,
        json={"vendor_id": str(vendor_id), "items": _lines(item)},
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["id"]

    session = await client.post(f"/orders/{order_id}/payment-session", headers=headers)
    assert session.status_code == 200, session.text
    await signed_webhook(_success_body(order_id))
    return order_id


async def _set_status(client, vendor_headers, order_id, status):
    return await client.patch(
        f"/vendors/me/orders/{order_id}/status",
        headers=vendor_headers,
        json={"status": status},
    )


async def _payment_status(db, order_id):
    from app.db.models.order import Order

    order = await db.get(Order, uuid.UUID(str(order_id)))
    await db.refresh(order)
    return order.payment_status


class TestTheRule:
    def test_every_ending_but_completed_owes_a_refund(self):
        """Read off the transition table, so a terminal status added later is
        refundable by default rather than by somebody remembering."""
        from app.db.models.order import OrderStatus
        from app.modules.orders.service import REFUNDABLE_ENDINGS, TERMINAL_STATUSES

        assert OrderStatus.COMPLETED not in REFUNDABLE_ENDINGS
        assert REFUNDABLE_ENDINGS == TERMINAL_STATUSES - {OrderStatus.COMPLETED}
        assert OrderStatus.REJECTED in REFUNDABLE_ENDINGS
        assert OrderStatus.CANCELLED in REFUNDABLE_ENDINGS

    def test_delivering_the_food_owes_nothing(self):
        from app.db.models.order import OrderStatus
        from app.modules.orders.service import REFUNDABLE_ENDINGS

        assert OrderStatus.COMPLETED not in REFUNDABLE_ENDINGS


class TestWhatTheStallDoes:
    async def test_rejecting_a_paid_order_still_refunds(
        self, stub_cashfree, signed_webhook, client, db, customer, vendor, menu_item
    ):
        from app.db.models.payment import PaymentStatus

        _, headers = customer
        v, vendor_headers = vendor
        order_id = await _paid_order(client, headers, v.id, menu_item, signed_webhook)

        r = await _set_status(client, vendor_headers, order_id, "rejected")
        assert r.status_code == 200, r.text

        assert await _payment_status(db, order_id) in (
            PaymentStatus.REFUND_PENDING,
            PaymentStatus.REFUNDED,
        )

    async def test_cancelling_a_paid_order_refunds_too(
        self, stub_cashfree, signed_webhook, client, db, customer, vendor, menu_item
    ):
        """The bug. This closed the order and kept the money."""
        from app.db.models.payment import PaymentStatus

        _, headers = customer
        v, vendor_headers = vendor
        order_id = await _paid_order(client, headers, v.id, menu_item, signed_webhook)

        r = await _set_status(client, vendor_headers, order_id, "cancelled")
        assert r.status_code == 200, r.text

        assert await _payment_status(db, order_id) in (
            PaymentStatus.REFUND_PENDING,
            PaymentStatus.REFUNDED,
        ), "a stall cancelling a paid order kept the customer's money"

    async def test_cancelling_after_accepting_also_refunds(
        self, stub_cashfree, signed_webhook, client, db, customer, vendor, menu_item
    ):
        """accepted -> cancelled is in the transition table, so it is reachable
        and has to carry the money with it."""
        from app.db.models.payment import PaymentStatus

        _, headers = customer
        v, vendor_headers = vendor
        order_id = await _paid_order(client, headers, v.id, menu_item, signed_webhook)

        assert (await _set_status(client, vendor_headers, order_id, "accepted")).status_code == 200
        r = await _set_status(client, vendor_headers, order_id, "cancelled")
        assert r.status_code == 200, r.text

        assert await _payment_status(db, order_id) in (
            PaymentStatus.REFUND_PENDING,
            PaymentStatus.REFUNDED,
        )

    async def test_completing_an_order_refunds_nothing(
        self, stub_cashfree, signed_webhook, client, db, customer, vendor, menu_item
    ):
        """The one ending where the customer got what they paid for."""
        from app.db.models.payment import PaymentStatus

        _, headers = customer
        v, vendor_headers = vendor
        order_id = await _paid_order(client, headers, v.id, menu_item, signed_webhook)

        for step in ("accepted", "preparing", "ready", "completed"):
            assert (
                await _set_status(client, vendor_headers, order_id, step)
            ).status_code == 200, step

        assert await _payment_status(db, order_id) is PaymentStatus.PAID


class TestStartRefundRefusesWhatItCannotDo:
    async def test_an_order_with_no_payment_row_is_not_left_pending(
        self, db, client, customer, vendor, menu_item
    ):
        """attempt_refund returns silently when there is no payment row, so
        moving the order to refund_pending anyway would strand it there for
        ever - and show an admin a refund in flight that nobody will make.

        Unreachable today, since paid implies a payment row. Pinned because the
        next settlement method that does not go through Cashfree will reach it.
        """
        from app.db.models.order import Order
        from app.db.models.payment import PaymentStatus
        from app.modules.payments import service as payments

        _, headers = customer
        v, _ = vendor
        r = await client.post(
            "/orders",
            headers=headers,
            json={"vendor_id": str(v.id), "items": _lines(menu_item)},
        )
        order = await db.get(Order, uuid.UUID(r.json()["id"]))
        order.payment_status = PaymentStatus.PAID
        await db.commit()

        await payments.start_refund(order.id, "no gateway behind this one", db)

        await db.refresh(order)
        assert order.payment_status is PaymentStatus.PAID


class TestTheDrain:
    def test_the_backoff_grows_and_then_stops_growing(self):
        """Doubling, capped at an hour. Long enough to outlast an incident,
        short enough that nobody is waiting on a human."""
        from app.modules.payments.service import _refund_backoff

        minutes = [_refund_backoff(n).total_seconds() / 60 for n in range(10)]
        assert minutes[:4] == [1, 2, 4, 8]
        assert all(b >= a for a, b in zip(minutes, minutes[1:]))
        assert max(minutes) == 60

    def test_it_gives_up_eventually(self):
        """Otherwise a permanently broken refund is re-driven on every single
        read of the orders page, for ever."""
        from app.modules.payments.service import MAX_REFUND_ATTEMPTS

        assert 1 < MAX_REFUND_ATTEMPTS <= 20

    async def test_a_stuck_refund_is_picked_up(
        self, db, client, customer, vendor, menu_item, pay, payments_on
    ):
        """The case the drain exists for: start_refund ran, the Cashfree call
        failed, and before this nothing ever tried again - refund_attempts was
        incremented and never read by anything."""
        from datetime import datetime, timedelta, timezone

        from fastapi import BackgroundTasks

        from app.db.models.order import Order
        from app.db.models.payment import Payment, PaymentStatus
        from app.modules.payments import service as payments

        _, headers = customer
        v, _ = vendor
        r = await client.post(
            "/orders",
            headers=headers,
            json={"vendor_id": str(v.id), "items": _lines(menu_item)},
        )
        order = await db.get(Order, uuid.UUID(r.json()["id"]))
        order.payment_status = PaymentStatus.REFUND_PENDING
        db.add(
            Payment(
                order_id=order.id,
                cf_order_id=f"cf_{order.id}",
                amount=order.total_amount,
                currency="INR",
                refund_attempts=1,
                updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )
        await db.commit()

        background = BackgroundTasks()
        started = await payments.drain_stuck_refunds(
            db, payments_on, background, customer_id=order.customer_id
        )

        assert started == 1

    async def test_a_refund_tried_moments_ago_is_left_alone(
        self, db, client, customer, vendor, menu_item, payments_on
    ):
        """Without the backoff, every refresh of the orders page would fire
        another Cashfree call at a refund that is already in flight."""
        from datetime import datetime, timezone

        from fastapi import BackgroundTasks

        from app.db.models.order import Order
        from app.db.models.payment import Payment, PaymentStatus
        from app.modules.payments import service as payments

        _, headers = customer
        v, _ = vendor
        r = await client.post(
            "/orders",
            headers=headers,
            json={"vendor_id": str(v.id), "items": _lines(menu_item)},
        )
        order = await db.get(Order, uuid.UUID(r.json()["id"]))
        order.payment_status = PaymentStatus.REFUND_PENDING
        db.add(
            Payment(
                order_id=order.id,
                cf_order_id=f"cf_{order.id}",
                amount=order.total_amount,
                currency="INR",
                refund_attempts=3,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

        started = await payments.drain_stuck_refunds(
            db, payments_on, BackgroundTasks(), customer_id=order.customer_id
        )

        assert started == 0

    async def test_one_customers_read_does_not_drain_another_customers_refunds(
        self, db, client, customer, vendor, menu_item, payments_on
    ):
        """Scoped like sweep_abandoned, so a busy read never turns into
        unbounded work across the whole table."""
        from datetime import datetime, timedelta, timezone

        from fastapi import BackgroundTasks

        from app.db.models.order import Order
        from app.db.models.payment import Payment, PaymentStatus
        from app.modules.payments import service as payments

        _, headers = customer
        v, _ = vendor
        r = await client.post(
            "/orders",
            headers=headers,
            json={"vendor_id": str(v.id), "items": _lines(menu_item)},
        )
        order = await db.get(Order, uuid.UUID(r.json()["id"]))
        order.payment_status = PaymentStatus.REFUND_PENDING
        db.add(
            Payment(
                order_id=order.id,
                cf_order_id=f"cf_{order.id}",
                amount=order.total_amount,
                currency="INR",
                refund_attempts=0,
                updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )
        await db.commit()

        started = await payments.drain_stuck_refunds(
            db, payments_on, BackgroundTasks(), customer_id=uuid.uuid4()
        )

        assert started == 0


class TestTheRouteIsGone:
    async def test_a_customer_can_no_longer_cancel(
        self, client, customer, vendor, menu_item
    ):
        """Removed rather than fixed: it called an unimported name and had been
        answering 500 for every caller, so there was no working behaviour to
        keep. A stale tab still calling it gets a 404, which the tracking page
        already renders as an error.
        """
        _, headers = customer
        v, _ = vendor
        r = await client.post(
            "/orders",
            headers=headers,
            json={"vendor_id": str(v.id), "items": _lines(menu_item)},
        )
        order_id = r.json()["id"]

        gone = await client.post(f"/orders/{order_id}/cancel", headers=headers)
        # 405 rather than 404 because the API is served alongside the web app's
        # static files, and the catch-all answers GET only. Either way the route
        # is gone and nothing cancels.
        assert gone.status_code in (404, 405), gone.text
