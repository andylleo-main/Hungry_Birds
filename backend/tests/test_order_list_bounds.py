"""The two order lists return a bounded slice, and never drop a live order.

Both used to return everything: every order a stall had ever served, every order
a student had ever placed, each with its items, customer and rider loaded. The
stall's is the one that hurt - the merchant app re-fetches it on every start and
every reconnect, so the cost grew for as long as the stall traded.

Bounding a list is easy to get subtly wrong, and the wrong way is the same in
both: a window on the date alone silently drops an order that is still being
cooked. So every test here has rows on both sides of the boundary, and the ones
that matter most are about what must *not* fall off.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

pytest.importorskip("httpx")

from app.db.models.order import FulfilmentType, Order, OrderStatus  # noqa: E402
from app.modules.orders.service import service_days_ago  # noqa: E402


async def _order(db, *, customer_id, vendor_id, status, created_at):
    row = Order(
        customer_id=customer_id,
        vendor_id=vendor_id,
        total_amount=Decimal("200.00"),
        # Unique per run: the suite can be pointed at a database that already
        # has rows, and a fixed number collides on the second go.
        order_number=f"{uuid.uuid4().int % 1000000:06d}-{uuid.uuid4().int % 10000:04d}",
        fulfilment_type=FulfilmentType.DINE_IN,
        status=status,
        created_at=created_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


class TestTheStallsQueue:
    async def test_it_carries_today_and_yesterday(self, client, db, vendor, customer):
        stall, vendor_headers = vendor
        user, _ = customer

        today = await _order(
            db,
            customer_id=user.id,
            vendor_id=stall.id,
            status=OrderStatus.COMPLETED,
            created_at=service_days_ago(0) + timedelta(hours=9),
        )
        yesterday = await _order(
            db,
            customer_id=user.id,
            vendor_id=stall.id,
            status=OrderStatus.COMPLETED,
            created_at=service_days_ago(1) + timedelta(hours=9),
        )

        body = (await client.get("/vendors/me/orders", headers=vendor_headers)).json()
        numbers = {o["order_number"] for o in body}

        assert today.order_number in numbers
        assert yesterday.order_number in numbers

    async def test_a_settled_order_from_last_week_is_gone(
        self, client, db, vendor, customer
    ):
        stall, vendor_headers = vendor
        user, _ = customer

        old = await _order(
            db,
            customer_id=user.id,
            vendor_id=stall.id,
            status=OrderStatus.COMPLETED,
            created_at=service_days_ago(7),
        )

        body = (await client.get("/vendors/me/orders", headers=vendor_headers)).json()

        assert old.order_number not in {o["order_number"] for o in body}

    async def test_an_unfinished_order_from_last_week_is_not(
        self, client, db, vendor, customer
    ):
        """**The one that must not be dropped.** A date window on its own would
        take an order still sitting in PREPARING straight out of the queue it is
        being cooked from - the single row on this screen that cannot be allowed
        to disappear."""
        stall, vendor_headers = vendor
        user, _ = customer

        stuck = await _order(
            db,
            customer_id=user.id,
            vendor_id=stall.id,
            status=OrderStatus.PREPARING,
            created_at=service_days_ago(7),
        )

        body = (await client.get("/vendors/me/orders", headers=vendor_headers)).json()

        assert stuck.order_number in {o["order_number"] for o in body}

    async def test_an_unpaid_checkout_is_still_hidden(
        self, client, db, vendor, customer
    ):
        """The older rule, which the new one must not have loosened: a stall has
        no business with an order until the money lands.

        Created *now*, not earlier today. This route sweeps abandoned checkouts
        before it builds the list, so one timestamped at nine this morning is
        past the gateway's expiry and comes back cancelled - which does belong in
        today's list, and would make this test assert the opposite of what it is
        about.
        """
        from datetime import datetime, timezone

        stall, vendor_headers = vendor
        user, _ = customer

        unpaid = await _order(
            db,
            customer_id=user.id,
            vendor_id=stall.id,
            status=OrderStatus.AWAITING_PAYMENT,
            created_at=datetime.now(timezone.utc),
        )

        body = (await client.get("/vendors/me/orders", headers=vendor_headers)).json()

        assert unpaid.order_number not in {o["order_number"] for o in body}


class TestAStudentsHistory:
    async def test_it_stops_at_a_page(self, client, db, vendor, customer, monkeypatch):
        """Patched down to 2 rather than building 51 orders: the property is
        "it stops", and 2 proves that as well as 50 does in a fraction of the
        time."""
        from app.modules.orders import router

        monkeypatch.setattr(router, "MY_ORDERS_PAGE", 2)

        stall, _ = vendor
        user, headers = customer

        made = []
        for days in (0, 1, 2, 3):
            made.append(
                await _order(
                    db,
                    customer_id=user.id,
                    vendor_id=stall.id,
                    status=OrderStatus.COMPLETED,
                    created_at=service_days_ago(days) + timedelta(hours=9),
                )
            )

        body = (await client.get("/orders", headers=headers)).json()
        numbers = {o["order_number"] for o in body}

        assert len(body) == 2
        # Newest first, so the two most recent survive and the older two do not.
        assert made[0].order_number in numbers
        assert made[1].order_number in numbers
        assert made[3].order_number not in numbers

    async def test_a_live_order_survives_the_page(
        self, client, db, vendor, customer, monkeypatch
    ):
        """The same rule as the stall's queue, for the same reason: the tracking
        page is the one a student watches, and an order being cooked must not
        age out from under them."""
        from app.modules.orders import router

        monkeypatch.setattr(router, "MY_ORDERS_PAGE", 2)

        stall, _ = vendor
        user, headers = customer

        for days in (0, 1, 2):
            await _order(
                db,
                customer_id=user.id,
                vendor_id=stall.id,
                status=OrderStatus.COMPLETED,
                created_at=service_days_ago(days) + timedelta(hours=9),
            )
        live = await _order(
            db,
            customer_id=user.id,
            vendor_id=stall.id,
            status=OrderStatus.PREPARING,
            created_at=service_days_ago(30),
        )

        body = (await client.get("/orders", headers=headers)).json()

        assert live.order_number in {o["order_number"] for o in body}

    async def test_another_students_orders_are_not_in_it(
        self, client, db, vendor, customer
    ):
        """Bounding a list is a place to accidentally widen it. The scope that
        matters is still the customer's own."""
        from app.db.models.user import User, UserRole

        stall, _ = vendor
        user, headers = customer

        stranger = User(
            email=f"other.{uuid.uuid4().hex[:8]}@bitmesra.ac.in", role=UserRole.CUSTOMER
        )
        db.add(stranger)
        await db.commit()
        await db.refresh(stranger)

        theirs = await _order(
            db,
            customer_id=stranger.id,
            vendor_id=stall.id,
            status=OrderStatus.COMPLETED,
            created_at=service_days_ago(0) + timedelta(hours=9),
        )

        body = (await client.get("/orders", headers=headers)).json()

        assert theirs.order_number not in {o["order_number"] for o in body}
