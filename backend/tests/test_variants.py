"""Dishes that come in sizes, and the one function that prices a line.

A dish is priced one of two ways: by its own column when it has no sizes, or by
the size the customer chose when it does. resolve_line_price is the only code
allowed to know which, and these tests pin both shapes plus the two ways a
client can get it wrong.

The ownership checks are the ones worth reading. A size is reachable only
through its dish, and a dish only through its stall, so a crafted payload cannot
pair a cheap size with an expensive dish or borrow a size from another stall's
menu. That chain is the only thing standing between a variant id and free food.
"""

import uuid
from decimal import Decimal

import pytest

pytest.importorskip("httpx")


async def _variant(client, headers, item_id, name, price, sort_order=0):
    r = await client.post(
        f"/vendors/me/items/{item_id}/variants",
        headers=headers,
        json={"name": name, "price": price, "sort_order": sort_order},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _order(client, headers, vendor_id, lines):
    return await client.post(
        "/orders", headers=headers, json={"vendor_id": str(vendor_id), "items": lines}
    )


class TestADishWithNoSizesIsUnchanged:
    async def test_it_still_orders_without_a_variant(
        self, client, customer, vendor, menu_item
    ):
        """Nothing was backfilled, so most dishes are this shape and must keep
        working exactly as before."""
        _, headers = customer
        v, _ = vendor

        r = await _order(
            client, headers, v.id, [{"menu_item_id": str(menu_item.id), "quantity": 2}]
        )

        assert r.status_code == 201, r.text
        assert r.json()["total_amount"] == "120.00"
        assert r.json()["items"][0]["variant_name_snapshot"] is None

    async def test_sending_a_size_it_does_not_have_is_refused(
        self, client, customer, vendor, menu_item
    ):
        """A client that thinks it is ordering something else."""
        _, headers = customer
        v, _ = vendor

        r = await _order(
            client,
            headers,
            v.id,
            [{"menu_item_id": str(menu_item.id), "variant_id": str(uuid.uuid4()), "quantity": 1}],
        )

        assert r.status_code in (400, 409), r.text

    async def test_price_from_is_just_the_price(self, client, vendor, menu_item):
        _, headers = vendor
        listing = await client.get("/vendors/me/items", headers=headers)
        mine = [i for i in listing.json() if i["id"] == str(menu_item.id)][0]
        assert mine["price_from"] == "60.00"
        assert mine["variants"] == []


class TestADishWithSizes:
    async def test_the_chosen_size_is_what_gets_charged(
        self, client, customer, vendor, menu_item
    ):
        v, vendor_headers = vendor
        _, headers = customer
        half = await _variant(client, vendor_headers, menu_item.id, "Half", "120.00")
        await _variant(client, vendor_headers, menu_item.id, "Full", "200.00", 1)

        r = await _order(
            client,
            headers,
            v.id,
            [{"menu_item_id": str(menu_item.id), "variant_id": half["id"], "quantity": 2}],
        )

        assert r.status_code == 201, r.text
        assert r.json()["total_amount"] == "240.00"

    async def test_the_size_is_snapshotted_beside_the_dish_name(
        self, client, customer, vendor, menu_item
    ):
        """Separate columns, so analytics can group by dish and still split by
        size. Folding them into one string destroys that."""
        v, vendor_headers = vendor
        _, headers = customer
        full = await _variant(client, vendor_headers, menu_item.id, "Full", "200.00")

        r = await _order(
            client,
            headers,
            v.id,
            [{"menu_item_id": str(menu_item.id), "variant_id": full["id"], "quantity": 1}],
        )

        line = r.json()["items"][0]
        assert line["name_snapshot"] == "Momos"
        assert line["variant_name_snapshot"] == "Full"
        assert line["price_snapshot"] == "200.00"

    async def test_ordering_without_choosing_a_size_is_refused(
        self, client, customer, vendor, menu_item
    ):
        """A dish with sizes has no meaningful single price, so there is nothing
        sensible to fall back to - including MenuItem.price, which is ignored
        once sizes exist."""
        v, vendor_headers = vendor
        _, headers = customer
        await _variant(client, vendor_headers, menu_item.id, "Half", "120.00")

        r = await _order(
            client, headers, v.id, [{"menu_item_id": str(menu_item.id), "quantity": 1}]
        )

        assert r.status_code in (400, 409), r.text

    async def test_price_from_is_the_cheapest_sellable_size(
        self, client, vendor, menu_item
    ):
        """So a card reads "from 120" rather than quoting the item's own column,
        which belongs to nothing once sizes exist."""
        _, headers = vendor
        await _variant(client, headers, menu_item.id, "Half", "120.00")
        await _variant(client, headers, menu_item.id, "Full", "200.00", 1)

        listing = await client.get("/vendors/me/items", headers=headers)
        mine = [i for i in listing.json() if i["id"] == str(menu_item.id)][0]
        assert mine["price_from"] == "120.00"

    async def test_a_sold_out_size_does_not_set_the_from_price(
        self, client, vendor, menu_item
    ):
        """Advertising "from 120" when the only 120 is finished is a lie on the
        storefront."""
        _, headers = vendor
        half = await _variant(client, headers, menu_item.id, "Half", "120.00")
        await _variant(client, headers, menu_item.id, "Full", "200.00", 1)

        await client.patch(
            f"/vendors/me/items/{menu_item.id}/variants/{half['id']}",
            headers=headers,
            json={"is_available": False},
        )

        listing = await client.get("/vendors/me/items", headers=headers)
        mine = [i for i in listing.json() if i["id"] == str(menu_item.id)][0]
        assert mine["price_from"] == "200.00"

    async def test_a_sold_out_size_cannot_be_ordered(
        self, client, customer, vendor, menu_item
    ):
        """"Full is finished, Half is still on" is the ordinary case, and the
        item-level flag cannot express it."""
        v, vendor_headers = vendor
        _, headers = customer
        full = await _variant(client, vendor_headers, menu_item.id, "Full", "200.00")
        await client.patch(
            f"/vendors/me/items/{menu_item.id}/variants/{full['id']}",
            headers=vendor_headers,
            json={"is_available": False},
        )

        r = await _order(
            client,
            headers,
            v.id,
            [{"menu_item_id": str(menu_item.id), "variant_id": full["id"], "quantity": 1}],
        )

        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "items_unavailable"
        assert "Full" in r.json()["detail"]["items"][0]["name"]


class TestTheOwnershipChain:
    async def test_a_size_from_another_dish_is_refused(
        self, client, db, customer, vendor, menu_item
    ):
        """Otherwise a payload pairs the cheapest size on the menu with the most
        expensive dish."""
        from app.db.models.menu import MenuItem

        v, vendor_headers = vendor
        _, headers = customer

        cheap = MenuItem(vendor_id=v.id, name="Chai", price=10, is_available=True)
        db.add(cheap)
        await db.commit()
        await db.refresh(cheap)
        small = await _variant(client, vendor_headers, cheap.id, "Small", "10.00")
        await _variant(client, vendor_headers, menu_item.id, "Full", "200.00")

        r = await _order(
            client,
            headers,
            v.id,
            [{"menu_item_id": str(menu_item.id), "variant_id": small["id"], "quantity": 1}],
        )

        assert r.status_code in (400, 409), r.text

    async def test_a_size_from_another_stall_is_refused(
        self, client, db, customer, vendor, menu_item
    ):
        from app.db.models.menu import MenuItem, MenuItemVariant
        from app.db.models.user import User, UserRole
        from app.db.models.vendor import Vendor

        v, vendor_headers = vendor
        _, headers = customer
        await _variant(client, vendor_headers, menu_item.id, "Full", "200.00")

        owner = User(
            email=f"rival.{uuid.uuid4().hex[:8]}@example.com",
            role=UserRole.VENDOR,
            phone="+919876500044",
        )
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        rival = Vendor(user_id=owner.id, stall_name="Rival", is_approved=True, is_open=True)
        db.add(rival)
        await db.commit()
        await db.refresh(rival)
        their_item = MenuItem(vendor_id=rival.id, name="Tea", price=5, is_available=True)
        db.add(their_item)
        await db.commit()
        await db.refresh(their_item)
        their_variant = MenuItemVariant(item_id=their_item.id, name="Small", price=Decimal("1.00"))
        db.add(their_variant)
        await db.commit()
        await db.refresh(their_variant)

        r = await _order(
            client,
            headers,
            v.id,
            [
                {
                    "menu_item_id": str(menu_item.id),
                    "variant_id": str(their_variant.id),
                    "quantity": 1,
                }
            ],
        )

        assert r.status_code in (400, 409), r.text

    async def test_a_stall_cannot_edit_another_stalls_size(
        self, client, db, vendor, menu_item
    ):
        from app.db.models.menu import MenuItem, MenuItemVariant
        from app.db.models.user import User, UserRole
        from app.db.models.vendor import Vendor

        _, headers = vendor

        owner = User(
            email=f"rival.{uuid.uuid4().hex[:8]}@example.com",
            role=UserRole.VENDOR,
            phone="+919876500055",
        )
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        rival = Vendor(user_id=owner.id, stall_name="Rival", is_approved=True, is_open=True)
        db.add(rival)
        await db.commit()
        await db.refresh(rival)
        their_item = MenuItem(vendor_id=rival.id, name="Tea", price=5, is_available=True)
        db.add(their_item)
        await db.commit()
        await db.refresh(their_item)
        their_variant = MenuItemVariant(item_id=their_item.id, name="Small", price=Decimal("5.00"))
        db.add(their_variant)
        await db.commit()
        await db.refresh(their_variant)

        r = await client.patch(
            f"/vendors/me/items/{their_item.id}/variants/{their_variant.id}",
            headers=headers,
            json={"name": "Hijacked"},
        )

        assert r.status_code == 404, r.text


class TestVariantPricesAreGatedToo:
    async def test_changing_a_size_price_waits_for_an_admin(
        self, client, db, vendor, menu_item
    ):
        """Without this the gate is trivially bypassed: a merchant with a frozen
        item price adds "Regular" at the number they wanted and sells at it."""
        from app.db.models.menu import MenuItemVariant

        _, headers = vendor
        half = await _variant(client, headers, menu_item.id, "Half", "120.00")

        r = await client.put(
            f"/vendors/me/items/{menu_item.id}/variants/{half['id']}/price",
            headers=headers,
            json={"price": "150.00"},
        )

        assert r.status_code == 200, r.text
        row = await db.get(MenuItemVariant, uuid.UUID(half["id"]))
        await db.refresh(row)
        assert row.price == Decimal("120.00")
        assert row.pending_price == Decimal("150.00")

    async def test_an_order_meanwhile_pays_the_old_size_price(
        self, client, customer, vendor, menu_item
    ):
        v, vendor_headers = vendor
        _, headers = customer
        half = await _variant(client, vendor_headers, menu_item.id, "Half", "120.00")
        await client.put(
            f"/vendors/me/items/{menu_item.id}/variants/{half['id']}/price",
            headers=vendor_headers,
            json={"price": "150.00"},
        )

        r = await _order(
            client,
            headers,
            v.id,
            [{"menu_item_id": str(menu_item.id), "variant_id": half["id"], "quantity": 1}],
        )

        assert r.json()["total_amount"] == "120.00"

    async def test_the_admin_queue_shows_the_dish_and_the_size(
        self, client, db, vendor, menu_item
    ):
        from app.core.security import TokenAudience, create_access_token
        from app.db.models.user import User, UserRole

        _, headers = vendor
        half = await _variant(client, headers, menu_item.id, "Half", "120.00")
        await client.put(
            f"/vendors/me/items/{menu_item.id}/variants/{half['id']}/price",
            headers=headers,
            json={"price": "150.00"},
        )

        admin_user = User(
            email=f"admin.{uuid.uuid4().hex[:10]}@bitmesra.ac.in",
            role=UserRole.ADMIN,
            phone="+919876500066",
        )
        db.add(admin_user)
        await db.commit()
        await db.refresh(admin_user)
        admin = {
            "Authorization": f"Bearer {create_access_token(str(admin_user.id), TokenAudience.WEB)}"
        }

        queue = await client.get("/admin/menu/price-changes", headers=admin)
        mine = [p for p in queue.json() if p["target_id"] == half["id"]]
        assert mine, "a pending size price never reached the queue"
        assert mine[0]["target"] == "variant"
        assert mine[0]["item_name"] == "Momos"
        assert mine[0]["variant_name"] == "Half"

    async def test_approving_a_size_price_moves_it(self, client, db, vendor, menu_item):
        from app.core.security import TokenAudience, create_access_token
        from app.db.models.menu import MenuItemVariant
        from app.db.models.user import User, UserRole

        _, headers = vendor
        half = await _variant(client, headers, menu_item.id, "Half", "120.00")
        await client.put(
            f"/vendors/me/items/{menu_item.id}/variants/{half['id']}/price",
            headers=headers,
            json={"price": "150.00"},
        )

        admin_user = User(
            email=f"admin.{uuid.uuid4().hex[:10]}@bitmesra.ac.in",
            role=UserRole.ADMIN,
            phone="+919876500077",
        )
        db.add(admin_user)
        await db.commit()
        await db.refresh(admin_user)
        admin = {
            "Authorization": f"Bearer {create_access_token(str(admin_user.id), TokenAudience.WEB)}"
        }

        r = await client.post(
            f"/admin/menu/price-changes/variant/{half['id']}/approve", headers=admin
        )

        assert r.status_code == 200, r.text
        row = await db.get(MenuItemVariant, uuid.UUID(half["id"]))
        await db.refresh(row)
        assert row.price == Decimal("150.00")
        assert row.pending_price is None


class TestNamingSizes:
    async def test_two_sizes_cannot_share_a_name(self, client, vendor, menu_item):
        """Two "Full"s leaves nobody able to say which one an order meant."""
        _, headers = vendor
        await _variant(client, headers, menu_item.id, "Full", "200.00")

        r = await client.post(
            f"/vendors/me/items/{menu_item.id}/variants",
            headers=headers,
            json={"name": "Full", "price": "250.00"},
        )

        assert r.status_code == 409, r.text

    async def test_the_clash_ignores_case(self, client, vendor, menu_item):
        _, headers = vendor
        await _variant(client, headers, menu_item.id, "Full", "200.00")

        r = await client.post(
            f"/vendors/me/items/{menu_item.id}/variants",
            headers=headers,
            json={"name": "full", "price": "250.00"},
        )

        assert r.status_code == 409, r.text

    async def test_sizes_come_back_in_the_order_the_stall_set(
        self, client, vendor, menu_item
    ):
        """Half before Full, rather than alphabetically."""
        _, headers = vendor
        await _variant(client, headers, menu_item.id, "Full", "200.00", 1)
        await _variant(client, headers, menu_item.id, "Half", "120.00", 0)

        listing = await client.get("/vendors/me/items", headers=headers)
        mine = [i for i in listing.json() if i["id"] == str(menu_item.id)][0]
        assert [v["name"] for v in mine["variants"]] == ["Half", "Full"]

    async def test_deleting_a_dish_takes_its_sizes(self, client, db, vendor, menu_item):
        """CASCADE, unlike a category, which deliberately leaves its dishes
        behind. A size has no meaning without its dish."""
        from sqlalchemy import select

        from app.db.models.menu import MenuItemVariant

        _, headers = vendor
        await _variant(client, headers, menu_item.id, "Half", "120.00")

        r = await client.delete(f"/vendors/me/items/{menu_item.id}", headers=headers)
        assert r.status_code == 204, r.text

        left = (
            await db.execute(
                select(MenuItemVariant).where(MenuItemVariant.item_id == menu_item.id)
            )
        ).scalars().all()
        assert left == []
