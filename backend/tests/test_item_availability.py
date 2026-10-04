"""What a customer is told when a dish sells out while it is in their cart.

This used to interpolate the menu item's UUID into a sentence and hand it
straight to the browser, which rendered it verbatim: "Menu item
3f8a1c2e-9b44-4d1e-8a21-7c0f5e2b9d10 is not available from this vendor". The
client was behaving correctly; the server was the problem.

It also refused on the first bad line, so a cart holding three sold-out dishes
had to be fixed one dish at a time, with a fresh attempt between each.

Both are pinned here, along with the thing that makes the "name the dish" fix
safe: names come only from the stall being ordered from, so this cannot be used
to read another stall's menu by guessing ids.
"""

import uuid

import pytest

pytest.importorskip("httpx")


async def _order(client, headers, vendor_id, lines):
    return await client.post(
        "/orders",
        headers=headers,
        json={"vendor_id": str(vendor_id), "items": lines},
    )


def _line(item_id, qty=1):
    return {"menu_item_id": str(item_id), "quantity": qty}


async def _sold_out(db, item):
    item.is_available = False
    await db.commit()
    await db.refresh(item)


async def _another_item(db, vendor, name="Chai", available=True):
    from app.db.models.menu import MenuItem

    item = MenuItem(vendor_id=vendor.id, name=name, price=20, is_available=available)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


class TestTheMessage:
    async def test_a_sold_out_dish_is_refused_with_a_code_the_client_can_act_on(
        self, client, db, customer, vendor, menu_item
    ):
        _, headers = customer
        v, _ = vendor
        await _sold_out(db, menu_item)

        r = await _order(client, headers, v.id, [_line(menu_item.id)])

        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "items_unavailable"

    async def test_it_names_the_dish(self, client, db, customer, vendor, menu_item):
        _, headers = customer
        v, _ = vendor
        await _sold_out(db, menu_item)

        r = await _order(client, headers, v.id, [_line(menu_item.id)])

        assert [i["name"] for i in r.json()["detail"]["items"]] == ["Momos"]

    async def test_no_uuid_reaches_anything_a_person_reads(
        self, client, db, customer, vendor, menu_item
    ):
        """The actual bug. The ids are still in the payload - the client needs
        them to strike the right lines through - but no human-facing string may
        contain one."""
        _, headers = customer
        v, _ = vendor
        await _sold_out(db, menu_item)

        detail = (await _order(client, headers, v.id, [_line(menu_item.id)])).json()["detail"]

        assert str(menu_item.id) not in detail["message"]
        assert all(str(menu_item.id) not in (i["name"] or "") for i in detail["items"])

    async def test_every_sold_out_line_is_reported_at_once(
        self, client, db, customer, vendor, menu_item
    ):
        """Refusing on the first one made a three-dish cart a three-attempt
        job, with the customer re-reading the same unhelpful sentence each
        time."""
        _, headers = customer
        v, _ = vendor
        second = await _another_item(db, v, name="Chai", available=False)
        third = await _another_item(db, v, name="Samosa", available=False)
        await _sold_out(db, menu_item)

        r = await _order(
            client,
            headers,
            v.id,
            [_line(menu_item.id), _line(second.id), _line(third.id)],
        )

        assert r.status_code == 409, r.text
        assert sorted(i["name"] for i in r.json()["detail"]["items"]) == [
            "Chai",
            "Momos",
            "Samosa",
        ]

    async def test_only_the_sold_out_lines_are_listed(
        self, client, db, customer, vendor, menu_item
    ):
        """So the client strikes through two dishes and leaves the third alone."""
        _, headers = customer
        v, _ = vendor
        gone = await _another_item(db, v, name="Chai", available=False)

        r = await _order(client, headers, v.id, [_line(menu_item.id), _line(gone.id)])

        assert [i["menu_item_id"] for i in r.json()["detail"]["items"]] == [str(gone.id)]


class TestWhatItWillNotSay:
    async def test_another_stalls_dish_is_refused_without_naming_it(
        self, client, db, customer, vendor, menu_item
    ):
        """Naming anything found by id would turn this into a way to read a
        competitor's menu by guessing. The lookup is scoped to the stall being
        ordered from, so somebody else's item is simply not found."""
        from app.db.models.menu import MenuItem
        from app.db.models.user import User, UserRole
        from app.db.models.vendor import Vendor

        _, headers = customer
        v, _ = vendor

        owner = User(
            email=f"rival.{uuid.uuid4().hex[:8]}@example.com",
            role=UserRole.VENDOR,
            phone="+919876500033",
        )
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        rival = Vendor(user_id=owner.id, stall_name="Rival", is_approved=True, is_open=True)
        db.add(rival)
        await db.commit()
        await db.refresh(rival)
        secret = MenuItem(
            vendor_id=rival.id, name="Secret Recipe", price=99, is_available=True
        )
        db.add(secret)
        await db.commit()
        await db.refresh(secret)

        r = await _order(client, headers, v.id, [_line(secret.id)])

        assert r.status_code == 409, r.text
        body = r.text
        assert "Secret Recipe" not in body
        assert r.json()["detail"]["items"][0]["name"] is None

    async def test_a_dish_the_stall_deleted_reports_no_name(
        self, client, db, customer, vendor, menu_item
    ):
        """There is nothing left to name. The client says "an item" rather than
        printing the id it was given."""
        _, headers = customer
        v, _ = vendor

        r = await _order(client, headers, v.id, [_line(uuid.uuid4())])

        assert r.status_code == 409, r.text
        assert r.json()["detail"]["items"][0]["name"] is None


class TestTheHappyPath:
    async def test_an_available_dish_still_orders(self, client, customer, vendor, menu_item):
        _, headers = customer
        v, _ = vendor

        r = await _order(client, headers, v.id, [_line(menu_item.id, 2)])

        assert r.status_code == 201, r.text
        assert r.json()["items"][0]["quantity"] == 2

    async def test_the_price_charged_is_the_stalls_price_not_the_clients(
        self, client, customer, vendor, menu_item
    ):
        """Batching the lookup must not become trusting the payload. The price
        still comes off the row the server read."""
        _, headers = customer
        v, _ = vendor

        r = await client.post(
            "/orders",
            headers=headers,
            json={
                "vendor_id": str(v.id),
                "items": [{"menu_item_id": str(menu_item.id), "quantity": 1, "price": "0.01"}],
            },
        )

        assert r.status_code == 201, r.text
        assert r.json()["total_amount"] == "60.00"

    async def test_the_same_dish_twice_in_one_cart_is_priced_twice(
        self, client, customer, vendor, menu_item
    ):
        """The batched lookup is keyed by id, so a repeated line must still be
        charged for - a dict lookup that silently collapsed duplicates would
        give away food."""
        _, headers = customer
        v, _ = vendor

        r = await _order(client, headers, v.id, [_line(menu_item.id), _line(menu_item.id)])

        assert r.status_code == 201, r.text
        assert r.json()["total_amount"] == "120.00"
