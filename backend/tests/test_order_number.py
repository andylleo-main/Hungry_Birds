"""The two numbers an order carries, and when each one is handed out.

They answer different questions and are pinned separately. order_number is
quoted on a support call and printed on a refund reference, so it has to be
unique forever and well-formed from the moment the row exists. token_number is
shouted across a counter, so it has to be small, per stall, and must not have
gaps that make a stall call out a number nobody was given.

The gap rule is the one worth reading twice: a token is allocated when an order
reaches the stall's queue, not when the row is created. Anything else spends
numbers on checkouts that were abandoned.
"""

import re
import uuid

import pytest

pytest.importorskip("httpx")

# NNNNNN-RRRR. Digits only, because this gets read aloud.
ORDER_NUMBER = re.compile(r"^\d{6}-\d{4}$")


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


class TestOrderNumber:
    async def test_an_order_has_one_from_the_moment_it_exists(
        self, client, customer, vendor, menu_item
    ):
        """Including before payment - an order nobody pays for still gets
        discussed, and support needs something to look it up by."""
        _, headers = customer
        v, _ = vendor
        order = await _place(client, headers, v.id, menu_item)

        assert ORDER_NUMBER.match(order["order_number"]), order["order_number"]

    async def test_it_is_digits_only(self, client, customer, vendor, menu_item):
        """No letters, deliberately. A letter alphabet read down a phone needs a
        "B as in Bombay" protocol, and this gets read down a phone."""
        _, headers = customer
        v, _ = vendor
        order = await _place(client, headers, v.id, menu_item)

        assert not any(c.isalpha() for c in order["order_number"])

    async def test_two_orders_never_share_one(self, client, customer, vendor, menu_item):
        _, headers = customer
        v, _ = vendor
        numbers = {
            (await _place(client, headers, v.id, menu_item))["order_number"] for _ in range(5)
        }
        assert len(numbers) == 5

    async def test_the_sequence_half_advances(self, client, customer, vendor, menu_item):
        """Uniqueness comes from the sequence, not from the random tail. If the
        leading digits ever stop moving, the only thing left keeping numbers
        apart is 1-in-10,000 luck."""
        _, headers = customer
        v, _ = vendor
        first = await _place(client, headers, v.id, menu_item)
        second = await _place(client, headers, v.id, menu_item)

        assert int(second["order_number"][:6]) > int(first["order_number"][:6])

    async def test_the_customer_sees_it_on_their_order(
        self, client, customer, vendor, menu_item
    ):
        _, headers = customer
        v, _ = vendor
        placed = await _place(client, headers, v.id, menu_item)

        fetched = await client.get(f"/orders/{placed['id']}", headers=headers)
        assert fetched.json()["order_number"] == placed["order_number"]


class TestTokenNumber:
    async def test_an_unpaid_order_has_no_token(self, client, customer, vendor, menu_item):
        """The whole point. A checkout nobody finishes must not burn a number,
        or the stall calls out 12 having never called 9, 10 or 11."""
        _, headers = customer
        v, _ = vendor
        order = await _place(client, headers, v.id, menu_item)

        assert order["status"] == "awaiting_payment"
        assert order["token_number"] is None

    async def test_paying_hands_out_the_token(
        self, client, db, customer, vendor, menu_item, pay
    ):
        from app.db.models.order import Order

        _, headers = customer
        v, _ = vendor
        placed = await _place(client, headers, v.id, menu_item)
        await pay(placed["id"])

        order = await db.get(Order, uuid.UUID(placed["id"]))
        await db.refresh(order)
        assert order.token_number is not None
        assert order.service_date is not None

    async def test_tokens_count_up_within_a_stall(
        self, client, db, customer, vendor, menu_item, pay
    ):
        from app.db.models.order import Order

        _, headers = customer
        v, _ = vendor
        tokens = []
        for _ in range(3):
            placed = await _place(client, headers, v.id, menu_item)
            await pay(placed["id"])
            order = await db.get(Order, uuid.UUID(placed["id"]))
            await db.refresh(order)
            tokens.append(order.token_number)

        assert tokens == [tokens[0], tokens[0] + 1, tokens[0] + 2]

    async def test_a_second_stall_counts_separately(self, client, db, customer, menu_item, pay):
        """Two stalls each call out their own "number 1". A platform-wide
        counter would have one of them calling 4,812."""
        from app.db.models.menu import MenuItem
        from app.db.models.order import Order
        from app.db.models.user import User, UserRole
        from app.db.models.vendor import Vendor

        _, headers = customer

        async def _fresh_stall():
            owner = User(
                email=f"stall.{uuid.uuid4().hex[:10]}@example.com",
                role=UserRole.VENDOR,
                phone="+919876500022",
            )
            db.add(owner)
            await db.commit()
            await db.refresh(owner)
            stall = Vendor(user_id=owner.id, stall_name="Another", is_approved=True, is_open=True)
            db.add(stall)
            await db.commit()
            await db.refresh(stall)
            item = MenuItem(vendor_id=stall.id, name="Tea", price=10, is_available=True)
            db.add(item)
            await db.commit()
            await db.refresh(item)
            return stall, item

        async def _first_token(stall, item):
            placed = await _place(client, headers, stall.id, item)
            await pay(placed["id"])
            order = await db.get(Order, uuid.UUID(placed["id"]))
            await db.refresh(order)
            return order.token_number

        stall_a, item_a = await _fresh_stall()
        stall_b, item_b = await _fresh_stall()

        assert await _first_token(stall_a, item_a) == 1
        assert await _first_token(stall_b, item_b) == 1

    async def test_allocating_twice_does_not_move_the_number(
        self, client, db, customer, vendor, menu_item, pay
    ):
        """Cashfree retries webhooks, and the mock route shares this path. A
        replayed success must not hand the same order a second token - the
        customer is already holding a slip with the first one."""
        from app.db.models.order import Order
        from app.modules.orders.service import allocate_token

        _, headers = customer
        v, _ = vendor
        placed = await _place(client, headers, v.id, menu_item)
        await pay(placed["id"])

        order = await db.get(Order, uuid.UUID(placed["id"]))
        await db.refresh(order)
        first = order.token_number

        await allocate_token(order, db)
        await db.commit()
        await db.refresh(order)

        assert order.token_number == first

    async def test_the_counter_does_not_skip_when_an_order_is_abandoned(
        self, client, db, customer, vendor, menu_item, pay
    ):
        """An abandoned checkout sits between two paid ones and must leave no
        hole. This is the behaviour allocating-on-payment exists for."""
        from app.db.models.order import Order

        _, headers = customer
        v, _ = vendor

        async def _paid_token():
            placed = await _place(client, headers, v.id, menu_item)
            await pay(placed["id"])
            order = await db.get(Order, uuid.UUID(placed["id"]))
            await db.refresh(order)
            return order.token_number

        before = await _paid_token()
        await _place(client, headers, v.id, menu_item)  # never paid
        after = await _paid_token()

        assert after == before + 1

    async def test_the_stall_sees_the_token_on_its_queue(
        self, client, customer, vendor, menu_item, pay
    ):
        """It is printed on the ticket and called across the counter, so it has
        to reach the merchant app, not just the database."""
        _, headers = customer
        v, vendor_headers = vendor
        placed = await _place(client, headers, v.id, menu_item)
        await pay(placed["id"])

        queue = await client.get("/vendors/me/orders", headers=vendor_headers)
        assert queue.status_code == 200, queue.text
        mine = [o for o in queue.json() if o["id"] == placed["id"]]
        assert mine, "the paid order never reached the stall's queue"
        assert mine[0]["token_number"] is not None
        assert ORDER_NUMBER.match(mine[0]["order_number"])
