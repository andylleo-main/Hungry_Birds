"""A stall's own numbers, and the figures it must never be shown.

The scoping tests are the point. The obvious way to build this - take the admin's
AnalyticsOut, filter it by vendor_id and ship it - would quietly hand every stall
`top_vendors`, which is a list of their competitors' revenue, reduced to one row
and looking perfectly correct in review. So the vendor response is a separate
model, and these tests assert the absence of those fields rather than trusting
that nobody adds them back.

The timezone test is the other one worth reading. These numbers get checked
against a cash box at the end of a day, and a UTC day starts at 05:30 IST.
"""

import uuid
from decimal import Decimal

import pytest

pytest.importorskip("httpx")


def _lines(item, qty=1):
    return [{"menu_item_id": str(item.id), "quantity": qty}]


async def _paid_order(client, headers, vendor_id, item, pay, qty=1):
    r = await client.post(
        "/orders",
        headers=headers,
        json={"vendor_id": str(vendor_id), "items": _lines(item, qty)},
    )
    assert r.status_code == 201, r.text
    await pay(r.json()["id"])
    return r.json()["id"]


async def _second_stall(db):
    from app.db.models.menu import MenuItem
    from app.db.models.user import User, UserRole
    from app.db.models.vendor import Vendor

    owner = User(
        email=f"other.{uuid.uuid4().hex[:10]}@example.com",
        role=UserRole.VENDOR,
        phone="+919876500088",
    )
    db.add(owner)
    await db.commit()
    await db.refresh(owner)
    stall = Vendor(user_id=owner.id, stall_name="Other Stall", is_approved=True, is_open=True)
    db.add(stall)
    await db.commit()
    await db.refresh(stall)
    item = MenuItem(vendor_id=stall.id, name="Tea", price=Decimal("25.00"), is_available=True)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return stall, item


class TestScoping:
    async def test_a_stall_sees_its_own_orders(
        self, client, customer, vendor, menu_item, pay
    ):
        _, headers = customer
        v, vendor_headers = vendor
        await _paid_order(client, headers, v.id, menu_item, pay)

        r = await client.get("/vendors/me/analytics", headers=vendor_headers)

        assert r.status_code == 200, r.text
        assert r.json()["totals"]["orders"] >= 1
        assert float(r.json()["totals"]["revenue"]) >= 60

    async def test_another_stalls_orders_are_not_counted(
        self, client, db, customer, vendor, menu_item, pay
    ):
        _, headers = customer
        v, vendor_headers = vendor
        other, other_item = await _second_stall(db)

        await _paid_order(client, headers, v.id, menu_item, pay)
        mine = (await client.get("/vendors/me/analytics", headers=vendor_headers)).json()

        await _paid_order(client, headers, other.id, other_item, pay)
        after = (await client.get("/vendors/me/analytics", headers=vendor_headers)).json()

        assert after["totals"]["orders"] == mine["totals"]["orders"], (
            "another stall's order moved this stall's numbers"
        )
        assert after["totals"]["revenue"] == mine["totals"]["revenue"]

    async def test_there_is_no_vendor_id_to_tamper_with(
        self, client, db, vendor, menu_item
    ):
        """Scoped by the signed-in stall, not by a parameter. A query argument
        would be one typo away from being honoured."""
        _, vendor_headers = vendor
        other, _ = await _second_stall(db)

        r = await client.get(
            f"/vendors/me/analytics?vendor_id={other.id}", headers=vendor_headers
        )

        assert r.status_code == 200, r.text
        # The parameter is simply not read; nothing changes shape because of it.
        assert "top_vendors" not in r.json()

    async def test_a_customer_cannot_read_a_stalls_numbers(
        self, client, customer
    ):
        _, headers = customer
        r = await client.get("/vendors/me/analytics", headers=headers)
        assert r.status_code in (401, 403, 404), r.text


class TestWhatItMustNotLeak:
    async def test_no_competitor_revenue(self, client, vendor):
        """top_vendors is the admin's list of every stall's takings. Filtering it
        to one row and shipping it would look right and be a leak."""
        _, headers = vendor
        body = (await client.get("/vendors/me/analytics", headers=headers)).json()
        assert "top_vendors" not in body

    async def test_no_platform_wide_counts(self, client, vendor):
        """How many customers the platform has is commercial information about
        the platform, not about this stall."""
        _, headers = vendor
        totals = (await client.get("/vendors/me/analytics", headers=headers)).json()["totals"]
        for leaked in ("customers", "vendors", "pending_vendors"):
            assert leaked not in totals, leaked

    def test_the_two_response_models_are_genuinely_separate(self):
        """Not the admin model with fields blanked out - absent, so they cannot
        come back by somebody populating them."""
        from app.modules.admin.analytics import AnalyticsOut
        from app.modules.vendors.analytics import VendorAnalyticsOut

        assert "top_vendors" in AnalyticsOut.model_fields
        assert "top_vendors" not in VendorAnalyticsOut.model_fields


class TestWhatAStallActuallyWants:
    async def test_top_dishes_come_back_with_quantities(
        self, client, customer, vendor, menu_item, pay
    ):
        _, headers = customer
        v, vendor_headers = vendor
        await _paid_order(client, headers, v.id, menu_item, pay, qty=3)

        body = (await client.get("/vendors/me/analytics", headers=vendor_headers)).json()

        mine = [d for d in body["top_dishes"] if d["name"] == "Momos"]
        assert mine, "nothing sold showed up in top dishes"
        assert mine[0]["quantity"] >= 3

    async def test_a_dish_groups_by_name_and_splits_by_size(
        self, client, customer, vendor, menu_item, pay
    ):
        """Why variant_name_snapshot is its own column: a stall wants the dish
        total and the size breakdown, and concatenating destroys the first."""
        _, headers = customer
        v, vendor_headers = vendor

        half = await client.post(
            f"/vendors/me/items/{menu_item.id}/variants",
            headers=vendor_headers,
            json={"name": "Half", "price": "120.00"},
        )
        full = await client.post(
            f"/vendors/me/items/{menu_item.id}/variants",
            headers=vendor_headers,
            json={"name": "Full", "price": "200.00", "sort_order": 1},
        )

        for variant in (half.json(), full.json()):
            r = await client.post(
                "/orders",
                headers=headers,
                json={
                    "vendor_id": str(v.id),
                    "items": [
                        {
                            "menu_item_id": str(menu_item.id),
                            "variant_id": variant["id"],
                            "quantity": 1,
                        }
                    ],
                },
            )
            assert r.status_code == 201, r.text
            await pay(r.json()["id"])

        body = (await client.get("/vendors/me/analytics", headers=vendor_headers)).json()
        sizes = {d["variant_name"] for d in body["top_dishes"] if d["name"] == "Momos"}
        assert {"Half", "Full"} <= sizes

    async def test_refusals_are_counted_and_priced(
        self, client, customer, vendor, menu_item, pay, stub_cashfree
    ):
        """A stall turning away one order in seven is about to lose its
        customers and has no other way to see it."""
        _, headers = customer
        v, vendor_headers = vendor
        order_id = await _paid_order(client, headers, v.id, menu_item, pay)

        await client.patch(
            f"/vendors/me/orders/{order_id}/status",
            headers=vendor_headers,
            json={"status": "rejected"},
        )

        totals = (await client.get("/vendors/me/analytics", headers=vendor_headers)).json()[
            "totals"
        ]
        assert totals["refused_orders"] >= 1
        assert float(totals["refused_value"]) >= 60

    async def test_a_rejected_order_is_not_revenue(
        self, client, customer, vendor, menu_item, pay, stub_cashfree
    ):
        _, headers = customer
        v, vendor_headers = vendor
        order_id = await _paid_order(client, headers, v.id, menu_item, pay)
        before = (await client.get("/vendors/me/analytics", headers=vendor_headers)).json()

        await client.patch(
            f"/vendors/me/orders/{order_id}/status",
            headers=vendor_headers,
            json={"status": "rejected"},
        )
        after = (await client.get("/vendors/me/analytics", headers=vendor_headers)).json()

        assert float(after["totals"]["revenue"]) < float(before["totals"]["revenue"])

    async def test_every_hour_is_present(self, client, vendor):
        """All twenty-four including the empty ones, so the shape of the day is
        readable and the chart does not change width between refreshes."""
        _, headers = vendor
        body = (await client.get("/vendors/me/analytics", headers=headers)).json()
        assert [h["hour"] for h in body["hours"]] == list(range(24))

    async def test_pending_price_changes_surface_on_the_dashboard(
        self, client, vendor, menu_item
    ):
        _, headers = vendor
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price", headers=headers, json={"price": "90.00"}
        )

        body = (await client.get("/vendors/me/analytics", headers=headers)).json()
        assert body["pending_price_changes"] == 1

    async def test_the_day_range_is_filled_in(self, client, vendor):
        """A quiet Tuesday has to be a trough, not a missing bar - an axis that
        skips it makes a bad week look like a steady one."""
        _, headers = vendor
        body = (await client.get("/vendors/me/analytics?days=7", headers=headers)).json()
        assert len(body["orders_by_day"]) == 7


class TestTheCalendarIsLocal:
    def test_days_and_hours_are_bucketed_in_ist(self):
        """A UTC day starts at 05:30 IST, which splits an evening rush across
        two bars and starts "today" mid-breakfast. Asserted on the source,
        because the alternative is a test that only fails between 00:00 and
        05:30 UTC."""
        from pathlib import Path

        source = Path("app/modules/vendors/analytics.py").read_text()
        assert 'IST = "Asia/Kolkata"' in source
        # Every time column goes through _local, so none of them can quietly
        # revert to UTC.
        assert "date_trunc(\"day\", _local(" in source
        assert 'func.extract("hour", _local(' in source
