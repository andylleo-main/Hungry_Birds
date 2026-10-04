"""A merchant proposes a price. An admin decides. Students keep paying the old one.

The gate is structural rather than a check somebody has to remember: the number
a merchant writes goes into `pending_price`, and nothing in any pricing path
reads that column. So an unapproved price cannot be charged because no code that
charges anything can see it. These tests pin that property from both directions -
the merchant cannot reach the live price, and the storefront keeps quoting it.

Two specific traps are pinned too, because both were live before this:

  * `update_item` assigned the payload in a loop, so any field added to
    `ItemUpdate` became writable. Price was on that schema, which made the gate
    bypassable by the most obvious request anybody would send.
  * The merchant app sends `price` on every save, even an untouched one. Taking
    "a price arrived" to mean "a price changed" would queue an approval every
    time somebody fixed a typo in a description.
"""

import uuid
from decimal import Decimal

import pytest

pytest.importorskip("httpx")


async def _admin(db):
    from app.core.security import TokenAudience, create_access_token
    from app.db.models.user import User, UserRole

    user = User(
        email=f"admin.{uuid.uuid4().hex[:10]}@bitmesra.ac.in",
        role=UserRole.ADMIN,
        phone="+919876500099",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"Authorization": f"Bearer {create_access_token(str(user.id), TokenAudience.WEB)}"}


async def _price_of(db, item_id):
    from app.db.models.menu import MenuItem

    item = await db.get(MenuItem, uuid.UUID(str(item_id)))
    await db.refresh(item)
    return item.price, item.pending_price


class TestTheMerchantCannotReachTheLivePrice:
    async def test_price_is_not_on_the_general_update_schema(self):
        """The bypass that was live. update_item assigns by name now, but the
        field being absent is the part that cannot be undone by a careless edit
        to the handler."""
        from app.modules.menu.schemas import ItemUpdate

        assert "price" not in ItemUpdate.model_fields

    async def test_pending_price_is_on_no_input_schema_at_all(self):
        """Output only, everywhere. A grep for pending_price should show a
        reader and never a writer."""
        from app.modules.menu import schemas

        for name in ("ItemCreate", "ItemUpdate", "VariantCreate", "VariantUpdate", "PriceUpdate"):
            model = getattr(schemas, name)
            assert "pending_price" not in model.model_fields, name

    async def test_patching_an_item_cannot_change_its_price(
        self, client, db, vendor, menu_item
    ):
        _, headers = vendor

        r = await client.patch(
            f"/vendors/me/items/{menu_item.id}",
            headers=headers,
            json={"name": "Momos", "price": "5.00"},
        )

        assert r.status_code == 200, r.text
        price, pending = await _price_of(db, menu_item.id)
        assert price == Decimal("60.00"), "a merchant set the live price through the update route"
        assert pending is None, "and it did not even queue it"


class TestProposingAPrice:
    async def test_the_live_price_does_not_move(self, client, db, vendor, menu_item):
        _, headers = vendor

        r = await client.put(
            f"/vendors/me/items/{menu_item.id}/price",
            headers=headers,
            json={"price": "90.00"},
        )

        assert r.status_code == 200, r.text
        price, pending = await _price_of(db, menu_item.id)
        assert price == Decimal("60.00")
        assert pending == Decimal("90.00")

    async def test_the_storefront_keeps_quoting_the_old_price(
        self, client, db, customer, vendor, menu_item
    ):
        """The product decision, and the reason this is the cheap design: there
        is no read filter to get wrong, because the gated number lives in a
        different column from the one that sells."""
        v, headers = vendor
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "90.00"}
        )

        _, customer_headers = customer
        detail = await client.get(f"/vendors/{v.id}", headers=customer_headers)
        assert detail.status_code == 200, detail.text
        items = detail.json()["uncategorized_items"] + [
            i for c in detail.json()["categories"] for i in c["items"]
        ]
        mine = [i for i in items if i["id"] == str(menu_item.id)]
        assert mine, "the dish vanished from the storefront while a price was pending"
        assert mine[0]["price"] == "60.00"

    async def test_an_order_placed_meanwhile_pays_the_old_price(
        self, client, customer, vendor, menu_item
    ):
        """The one that actually matters."""
        v, vendor_headers = vendor
        _, headers = customer
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price",
            headers=vendor_headers,
            json={"price": "90.00"},
        )

        order = await client.post(
            "/orders",
            headers=headers,
            json={
                "vendor_id": str(v.id),
                "items": [{"menu_item_id": str(menu_item.id), "quantity": 1}],
            },
        )
        assert order.status_code == 201, order.text
        assert order.json()["total_amount"] == "60.00"

    async def test_the_merchant_sees_it_waiting(self, client, vendor, menu_item):
        _, headers = vendor
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "90.00"}
        )

        listing = await client.get("/vendors/me/items", headers=headers)
        mine = [i for i in listing.json() if i["id"] == str(menu_item.id)][0]
        assert mine["price_awaiting_approval"] is True
        assert mine["pending_price"] == "90.00"


class TestTheNoOpSave:
    async def test_resending_the_same_price_queues_nothing(
        self, client, db, vendor, menu_item
    ):
        """The merchant app sends price on every save. Without this, fixing a
        typo in a description files a price approval, and an admin cannot tell
        those from real requests."""
        _, headers = vendor

        r = await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "60.00"}
        )

        assert r.status_code == 200, r.text
        _, pending = await _price_of(db, menu_item.id)
        assert pending is None

    async def test_the_same_amount_written_differently_still_counts_as_unchanged(
        self, client, db, vendor, menu_item
    ):
        """60, 60.0 and 60.00 are one price. The client sends a JSON number and
        the column is Numeric(10,2), so comparing them raw reads an untouched
        price as a change - the same trap _amounts_match handles for payments."""
        _, headers = vendor

        for written in ("60", "60.0", "60.000"):
            await client.put(
                f"/vendors/me/items/{menu_item.id}/price",
                headers=headers,
                json={"price": written},
            )
            _, pending = await _price_of(db, menu_item.id)
            assert pending is None, written

    async def test_typing_the_old_price_back_withdraws_a_pending_change(
        self, client, db, vendor, menu_item
    ):
        """What a merchant means by it: never mind."""
        _, headers = vendor
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "90.00"}
        )

        await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "60.00"}
        )

        _, pending = await _price_of(db, menu_item.id)
        assert pending is None

    async def test_a_merchant_can_withdraw_a_mistake_without_waiting_for_a_human(
        self, client, db, vendor, menu_item
    ):
        """Somebody who typed 2000 instead of 200 should not need an admin."""
        _, headers = vendor
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "2000.00"}
        )

        r = await client.delete(f"/vendors/me/items/{menu_item.id}/price", headers=headers)

        assert r.status_code == 200, r.text
        price, pending = await _price_of(db, menu_item.id)
        assert pending is None
        assert price == Decimal("60.00")

    async def test_a_second_proposal_replaces_the_first(self, client, db, vendor, menu_item):
        """At most one pending change per dish, by construction. A merchant who
        changes their mind means the newer number."""
        _, headers = vendor
        for p in ("90.00", "75.00"):
            await client.put(
                f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": p}
            )

        _, pending = await _price_of(db, menu_item.id)
        assert pending == Decimal("75.00")


class TestTheAdminDecides:
    async def test_approving_moves_the_live_price(self, client, db, vendor, menu_item):
        _, headers = vendor
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "90.00"}
        )
        admin = await _admin(db)

        r = await client.post(
            f"/admin/menu/price-changes/item/{menu_item.id}/approve", headers=admin
        )

        assert r.status_code == 200, r.text
        price, pending = await _price_of(db, menu_item.id)
        assert price == Decimal("90.00")
        assert pending is None

    async def test_rejecting_leaves_the_old_price_alone(self, client, db, vendor, menu_item):
        _, headers = vendor
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "90.00"}
        )
        admin = await _admin(db)

        r = await client.post(
            f"/admin/menu/price-changes/item/{menu_item.id}/reject", headers=admin
        )

        assert r.status_code == 200, r.text
        price, pending = await _price_of(db, menu_item.id)
        assert price == Decimal("60.00")
        assert pending is None

    async def test_deciding_twice_says_there_is_nothing_to_decide(
        self, client, db, vendor, menu_item
    ):
        """The panel's list can be stale. Silently approving a price that is no
        longer proposed is the wrong answer."""
        _, headers = vendor
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "90.00"}
        )
        admin = await _admin(db)
        await client.post(f"/admin/menu/price-changes/item/{menu_item.id}/approve", headers=admin)

        again = await client.post(
            f"/admin/menu/price-changes/item/{menu_item.id}/approve", headers=admin
        )

        assert again.status_code == 404, again.text

    async def test_the_queue_lists_what_is_waiting(self, client, db, vendor, menu_item):
        _, headers = vendor
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "90.00"}
        )
        admin = await _admin(db)

        queue = await client.get("/admin/menu/price-changes", headers=admin)

        assert queue.status_code == 200, queue.text
        mine = [p for p in queue.json() if p["target_id"] == str(menu_item.id)]
        assert mine, "a pending change did not reach the queue"
        assert mine[0]["current_price"] == "60.00"
        assert mine[0]["pending_price"] == "90.00"
        assert mine[0]["pct_change"] == 50.0
        assert mine[0]["stall_name"]

    async def test_a_merchant_cannot_work_the_queue(self, client, vendor, menu_item):
        """The gate would be decorative otherwise."""
        _, headers = vendor
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "90.00"}
        )

        assert (await client.get("/admin/menu/price-changes", headers=headers)).status_code in (
            401,
            403,
        )
        assert (
            await client.post(
                f"/admin/menu/price-changes/item/{menu_item.id}/approve", headers=headers
            )
        ).status_code in (401, 403)

    async def test_the_decision_is_recorded_against_the_admin(
        self, client, db, vendor, menu_item
    ):
        from sqlalchemy import select

        from app.db.models.menu import MenuPriceChange, PriceChangeKind

        _, headers = vendor
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "90.00"}
        )
        admin = await _admin(db)
        await client.post(f"/admin/menu/price-changes/item/{menu_item.id}/approve", headers=admin)

        rows = (
            await db.execute(
                select(MenuPriceChange).where(MenuPriceChange.item_id == menu_item.id)
            )
        ).scalars().all()
        kinds = {r.kind for r in rows}
        assert PriceChangeKind.REQUESTED in kinds
        assert PriceChangeKind.APPROVED in kinds
        approved = [r for r in rows if r.kind == PriceChangeKind.APPROVED][0]
        assert approved.decided_by is not None


class TestTheBypassIsRecordedRatherThanClaimedClosed:
    async def test_creating_a_dish_is_not_gated(self, client, db, vendor):
        """Deliberate. Gating creation would mean a new dish is unsellable until
        an admin wakes up."""
        _, headers = vendor

        r = await client.post(
            "/vendors/me/items", headers=headers, json={"name": "New Thing", "price": "500.00"}
        )

        assert r.status_code == 201, r.text
        assert r.json()["price"] == "500.00"
        assert r.json()["price_awaiting_approval"] is False

    async def test_but_it_leaves_a_trail(self, client, db, vendor):
        """Add-new-then-delete-old is the way round the gate and cannot be
        closed without gating creation. So it is made visible instead: the
        history carries created prices too, and an admin can see a stall that
        replaced six dishes in a week."""
        from sqlalchemy import select

        from app.db.models.menu import MenuPriceChange, PriceChangeKind

        v, headers = vendor
        r = await client.post(
            "/vendors/me/items", headers=headers, json={"name": "New Thing", "price": "500.00"}
        )

        rows = (
            await db.execute(
                select(MenuPriceChange).where(
                    MenuPriceChange.item_id == uuid.UUID(r.json()["id"])
                )
            )
        ).scalars().all()
        assert [row.kind for row in rows] == [PriceChangeKind.CREATED]
        assert rows[0].new_price == Decimal("500.00")
        assert rows[0].old_price is None
