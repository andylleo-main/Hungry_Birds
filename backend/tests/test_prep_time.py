"""Telling a student how long their food will take.

Two numbers feed one promise. The menu's own per-dish times give an estimate at
placement; the merchant can replace the kitchen half of it when they accept,
because they are the one looking at the actual stove. The delivery buffer is
added on top of whichever won, so a merchant never has to think about riders.

The thing most worth protecting here is the silence: a stall that has not filled
in any prep times gets no estimate at all, rather than a number somebody made up.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("httpx")


def _lines(item, qty=1):
    return [{"menu_item_id": str(item.id), "quantity": qty}]


# --- the formula ------------------------------------------------------------


class TestTheFormula:
    """A kitchen cooks in parallel, so an order is not the sum of its dishes."""

    def test_the_example_the_stall_asked_for(self):
        from app.modules.orders.service import estimate_prep_minutes

        # 1 Paneer Chilli (15 min) and 4 Roti (5 min).
        assert estimate_prep_minutes([15, 5]) == 17

    def test_one_dish_is_its_own_time(self):
        from app.modules.orders.service import estimate_prep_minutes

        assert estimate_prep_minutes([15]) == 15

    def test_each_extra_dish_adds_two_minutes(self):
        from app.modules.orders.service import estimate_prep_minutes

        assert estimate_prep_minutes([15, 5, 8]) == 19
        assert estimate_prep_minutes([15, 5, 8, 3]) == 21

    def test_quantity_is_not_in_it(self):
        """Four rotis are one pan.

        The caller passes one entry per distinct dish, which is why this takes
        times rather than lines - summing quantities would make a roti order read
        as half an hour and nobody would wait.
        """
        from app.modules.orders.service import estimate_prep_minutes

        assert estimate_prep_minutes([5]) == 5

    def test_dishes_with_no_time_are_ignored_entirely(self):
        """A bottle of water neither takes time nor costs a hand-off.

        Ignored rather than counted as zero: counting it would add two minutes
        for lifting a bottle out of a fridge.
        """
        from app.modules.orders.service import estimate_prep_minutes

        assert estimate_prep_minutes([15, None, None]) == 15

    def test_no_times_at_all_means_no_estimate(self):
        """The silence that matters.

        A stall that has filled nothing in says nothing, rather than having a
        number invented on its behalf.
        """
        from app.modules.orders.service import estimate_prep_minutes

        assert estimate_prep_minutes([None, None]) is None
        assert estimate_prep_minutes([]) is None

    def test_a_mistyped_time_cannot_promise_tomorrow(self):
        from app.modules.orders.service import MAX_PREP_MINUTES, estimate_prep_minutes

        assert estimate_prep_minutes([240, 240, 240]) == MAX_PREP_MINUTES


class TestTheDeliveryBuffer:
    def test_delivery_adds_fifteen_and_dine_in_adds_nothing(self):
        from app.db.models.order import FulfilmentType
        from app.modules.orders.service import ready_by_from

        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

        dine_in = ready_by_from(15, FulfilmentType.DINE_IN, now=now)
        delivery = ready_by_from(15, FulfilmentType.DELIVERY, now=now)

        assert dine_in == now + timedelta(minutes=15)
        assert delivery == now + timedelta(minutes=30)

    def test_no_prep_time_means_no_promise_either_way(self):
        from app.db.models.order import FulfilmentType
        from app.modules.orders.service import ready_by_from

        assert ready_by_from(None, FulfilmentType.DELIVERY) is None


# --- the menu ---------------------------------------------------------------


class TestTheMerchantsMenu:
    async def test_a_prep_time_saves_without_an_admin(self, client, db, vendor, menu_item):
        """The deliberate asymmetry with price.

        A wrong prep time costs a few minutes of goodwill and the merchant fixes
        it themselves. A wrong price costs money. Only one of them is worth an
        admin standing in the way, and this test is what says so.
        """
        from sqlalchemy import select

        from app.db.models.menu import MenuItem, MenuPriceChange

        _, headers = vendor

        r = await client.patch(
            f"/vendors/me/items/{menu_item.id}", headers=headers, json={"prep_minutes": 12}
        )
        assert r.status_code == 200, r.text
        assert r.json()["prep_minutes"] == 12

        row = await db.get(MenuItem, menu_item.id)
        await db.refresh(row)
        assert row.prep_minutes == 12

        # Nothing queued for anybody to approve.
        pending = (
            await db.execute(
                select(MenuPriceChange).where(MenuPriceChange.item_id == menu_item.id)
            )
        ).scalars().all()
        assert pending == []

    async def test_a_price_still_cannot_ride_along_with_it(self, client, vendor, menu_item):
        """prep_minutes being writable here must not reopen the price door."""
        _, headers = vendor
        r = await client.patch(
            f"/vendors/me/items/{menu_item.id}",
            headers=headers,
            json={"prep_minutes": 12, "price": "1.00"},
        )
        assert r.status_code == 422

    async def test_an_absurd_time_is_refused(self, client, vendor, menu_item):
        _, headers = vendor
        for bad in (0, -5, 999):
            r = await client.patch(
                f"/vendors/me/items/{menu_item.id}", headers=headers, json={"prep_minutes": bad}
            )
            assert r.status_code == 422, f"{bad} should be refused"

    async def test_it_reaches_the_storefront(self, client, vendor, customer, menu_item):
        """Which is the whole point - a student picks the fast dish."""
        v, headers = vendor
        _, student = customer
        await client.patch(
            f"/vendors/me/items/{menu_item.id}", headers=headers, json={"prep_minutes": 9}
        )

        # Read as a customer: the storefront is behind sign-in.
        shown = await client.get(f"/vendors/{v.id}", headers=student)
        assert shown.status_code == 200, shown.text
        items = shown.json()["uncategorized_items"] + [
            i for c in shown.json()["categories"] for i in c["items"]
        ]
        mine = next(i for i in items if i["id"] == str(menu_item.id))
        assert mine["prep_minutes"] == 9

    async def test_a_dish_with_no_time_says_so_rather_than_zero(
        self, client, vendor, customer, menu_item
    ):
        v, _ = vendor
        _, student = customer
        shown = await client.get(f"/vendors/{v.id}", headers=student)
        items = shown.json()["uncategorized_items"] + [
            i for c in shown.json()["categories"] for i in c["items"]
        ]
        mine = next(i for i in items if i["id"] == str(menu_item.id))
        assert mine["prep_minutes"] is None


# --- an order ---------------------------------------------------------------


class TestWhatTheCustomerIsTold:
    async def test_an_order_carries_the_estimate_from_the_menu(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        from app.db.models.order import Order

        v, vendor_headers = vendor
        _, headers = customer
        await client.patch(
            f"/vendors/me/items/{menu_item.id}", headers=vendor_headers, json={"prep_minutes": 15}
        )

        r = await client.post(
            "/orders", headers=headers, json={"vendor_id": str(v.id), "items": _lines(menu_item)}
        )
        assert r.status_code == 201, r.text
        assert r.json()["prep_minutes"] == 15
        assert r.json()["ready_by"] is not None

        row = await db.get(Order, uuid.UUID(r.json()["id"]))
        await db.refresh(row)
        # Dine-in, so no buffer.
        assert row.ready_by - row.created_at < timedelta(minutes=16)

    async def test_a_delivery_is_promised_fifteen_minutes_later(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        from app.db.models.order import Order

        v, vendor_headers = vendor
        _, headers = customer
        await client.patch(
            f"/vendors/me/items/{menu_item.id}", headers=vendor_headers, json={"prep_minutes": 15}
        )

        r = await client.post(
            "/orders",
            headers=headers,
            json={
                "vendor_id": str(v.id),
                "items": _lines(menu_item),
                "fulfilment_type": "delivery",
                "delivery_location": "hostel_3",
            },
        )
        assert r.status_code == 201, r.text
        # The kitchen number is unchanged; the buffer is not a prep time.
        assert r.json()["prep_minutes"] == 15

        row = await db.get(Order, uuid.UUID(r.json()["id"]))
        await db.refresh(row)
        gap = row.ready_by - row.created_at
        assert timedelta(minutes=29) < gap < timedelta(minutes=31)

    async def test_a_stall_with_no_prep_times_promises_nothing(
        self, stub_razorpay, client, customer, vendor, menu_item
    ):
        v, _ = vendor
        _, headers = customer
        r = await client.post(
            "/orders", headers=headers, json={"vendor_id": str(v.id), "items": _lines(menu_item)}
        )
        assert r.status_code == 201
        assert r.json()["prep_minutes"] is None
        assert r.json()["ready_by"] is None

    async def test_editing_the_dish_later_does_not_rewrite_the_promise(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        """Snapshotted, exactly as line prices are.

        A merchant doubling a dish's prep time this afternoon must not change
        what somebody was told this morning.
        """
        from app.db.models.order import Order

        v, vendor_headers = vendor
        _, headers = customer
        await client.patch(
            f"/vendors/me/items/{menu_item.id}", headers=vendor_headers, json={"prep_minutes": 10}
        )
        order = (
            await client.post(
                "/orders", headers=headers, json={"vendor_id": str(v.id), "items": _lines(menu_item)}
            )
        ).json()
        assert order["prep_minutes"] == 10

        await client.patch(
            f"/vendors/me/items/{menu_item.id}", headers=vendor_headers, json={"prep_minutes": 45}
        )

        row = await db.get(Order, uuid.UUID(order["id"]))
        await db.refresh(row)
        assert row.prep_minutes == 10


# --- the merchant's own number ----------------------------------------------


class TestAcceptingWithATime:
    async def _placed(self, client, db, headers, vendor_headers, v, menu_item, prep=15, **extra):
        await client.patch(
            f"/vendors/me/items/{menu_item.id}",
            headers=vendor_headers,
            json={"prep_minutes": prep},
        )
        r = await client.post(
            "/orders",
            headers=headers,
            json={"vendor_id": str(v.id), "items": _lines(menu_item), **extra},
        )
        assert r.status_code == 201, r.text
        order = r.json()

        from app.db.models.order import Order, OrderStatus
        from app.db.models.payment import PaymentStatus

        row = await db.get(Order, uuid.UUID(order["id"]))
        if row.status is OrderStatus.AWAITING_PAYMENT:
            row.status = OrderStatus.PLACED
            row.payment_status = PaymentStatus.PAID
            await db.commit()
        return order

    async def test_the_merchants_number_wins(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        from app.db.models.order import Order

        v, vendor_headers = vendor
        _, headers = customer
        order = await self._placed(client, db, headers, vendor_headers, v, menu_item, prep=15)

        r = await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "accepted", "prep_minutes": 25},
        )
        assert r.status_code == 200, r.text
        assert r.json()["prep_minutes"] == 25

        row = await db.get(Order, uuid.UUID(order["id"]))
        await db.refresh(row)
        assert row.prep_minutes == 25

    async def test_accepting_without_one_keeps_the_suggestion(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        """Which is what the merchant app pre-fills the field with.

        So "accept without thinking about it" and "accept the suggested number"
        are the same action, rather than one of them wiping the estimate.
        """
        v, vendor_headers = vendor
        _, headers = customer
        order = await self._placed(client, db, headers, vendor_headers, v, menu_item, prep=15)

        r = await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "accepted"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["prep_minutes"] == 15

    async def test_the_merchants_number_is_prep_only_and_the_buffer_still_applies(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        """A merchant answering "how long to cook this" never thinks about riders."""
        from app.db.models.order import Order

        v, vendor_headers = vendor
        _, headers = customer
        order = await self._placed(
            client,
            db,
            headers,
            vendor_headers,
            v,
            menu_item,
            prep=15,
            fulfilment_type="delivery",
            delivery_location="hostel_3",
        )

        before = datetime.now(timezone.utc)
        r = await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "accepted", "prep_minutes": 20},
        )
        assert r.json()["prep_minutes"] == 20

        row = await db.get(Order, uuid.UUID(order["id"]))
        await db.refresh(row)
        gap = row.ready_by - before
        # 20 of cooking plus the 15 the merchant never had to think about.
        assert timedelta(minutes=34) < gap < timedelta(minutes=36)

    async def test_the_clock_restarts_when_the_kitchen_takes_it_on(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        """Otherwise an order accepted late shows a countdown already run out."""
        from app.db.models.order import Order

        v, vendor_headers = vendor
        _, headers = customer
        order = await self._placed(client, db, headers, vendor_headers, v, menu_item, prep=15)

        # Stand in for the order having sat unaccepted for half an hour.
        row = await db.get(Order, uuid.UUID(order["id"]))
        row.ready_by = datetime.now(timezone.utc) - timedelta(minutes=30)
        await db.commit()

        await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "accepted"},
        )

        await db.refresh(row)
        assert row.ready_by > datetime.now(timezone.utc)

    async def test_a_time_sent_on_any_other_move_is_ignored(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        """Marking something ready is not re-answering how long it takes."""
        from app.db.models.order import Order

        v, vendor_headers = vendor
        _, headers = customer
        order = await self._placed(client, db, headers, vendor_headers, v, menu_item, prep=15)

        await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "accepted", "prep_minutes": 20},
        )
        await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "preparing", "prep_minutes": 99},
        )

        row = await db.get(Order, uuid.UUID(order["id"]))
        await db.refresh(row)
        assert row.prep_minutes == 20

    async def test_an_absurd_time_is_refused_here_too(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        v, vendor_headers = vendor
        _, headers = customer
        order = await self._placed(client, db, headers, vendor_headers, v, menu_item, prep=15)

        r = await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "accepted", "prep_minutes": 999},
        )
        assert r.status_code == 422

    async def test_a_stall_can_put_a_time_on_an_order_that_had_none(
        self, stub_razorpay, client, db, customer, vendor, menu_item
    ):
        """The menu said nothing, but the merchant knows.

        Worth having: a stall that never filled in its menu times can still
        answer the one question a waiting student is actually asking.
        """
        from app.db.models.order import Order

        v, vendor_headers = vendor
        _, headers = customer
        r = await client.post(
            "/orders", headers=headers, json={"vendor_id": str(v.id), "items": _lines(menu_item)}
        )
        order = r.json()
        assert order["prep_minutes"] is None

        from app.db.models.order import OrderStatus
        from app.db.models.payment import PaymentStatus

        row = await db.get(Order, uuid.UUID(order["id"]))
        row.status = OrderStatus.PLACED
        row.payment_status = PaymentStatus.PAID
        await db.commit()

        accepted = await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "accepted", "prep_minutes": 12},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["prep_minutes"] == 12
        assert accepted.json()["ready_by"] is not None
