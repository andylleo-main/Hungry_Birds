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
        self, client, customer, vendor, menu_item, pay, stub_razorpay
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
        self, client, customer, vendor, menu_item, pay, stub_razorpay
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

    async def test_a_waiting_size_price_is_counted_too(self, client, vendor, menu_item):
        """A price can be pending on a size as well as on the dish itself.

        This counted only MenuItem.pending_price, so a stall whose one waiting
        change was on "Half" was told nothing was waiting - while the admin
        queue, which unions both shapes, was showing it the whole time. The
        merchant's only signal that an admin had not got to it yet said zero.
        """
        _, headers = vendor
        variant = await client.post(
            f"/vendors/me/items/{menu_item.id}/variants",
            headers=headers,
            json={"name": "Half", "price": "120.00"},
        )
        assert variant.status_code == 201, variant.text
        r = await client.put(
            f"/vendors/me/items/{menu_item.id}/variants/{variant.json()['id']}/price",
            headers=headers,
            json={"price": "150.00"},
        )
        assert r.status_code == 200, r.text

        body = (await client.get("/vendors/me/analytics", headers=headers)).json()
        assert body["pending_price_changes"] == 1

    async def test_both_shapes_add_up(self, client, vendor, menu_item):
        """The dish and one of its sizes, waiting at the same time: two."""
        _, headers = vendor
        variant = await client.post(
            f"/vendors/me/items/{menu_item.id}/variants",
            headers=headers,
            json={"name": "Half", "price": "120.00"},
        )
        await client.put(
            f"/vendors/me/items/{menu_item.id}/variants/{variant.json()['id']}/price",
            headers=headers,
            json={"price": "150.00"},
        )
        await client.put(
            f"/vendors/me/items/{menu_item.id}/price",
            headers=headers,
            json={"price": "90.00"},
        )

        body = (await client.get("/vendors/me/analytics", headers=headers)).json()
        assert body["pending_price_changes"] == 2

    async def test_another_stalls_waiting_size_is_not_counted(
        self, client, db, vendor, menu_item
    ):
        """The join reaches the stall through the dish, so it has to be the
        right stall's dish. A count that leaked across stalls would show every
        merchant on campus the same number."""
        from app.db.models.menu import MenuItem, MenuItemVariant
        from app.db.models.user import User, UserRole
        from app.db.models.vendor import Vendor

        _, headers = vendor
        owner = User(
            email=f"rival.{uuid.uuid4().hex[:8]}@example.com",
            role=UserRole.VENDOR,
            phone="+919876500077",
        )
        db.add(owner)
        await db.commit()
        await db.refresh(owner)
        other = Vendor(
            user_id=owner.id, stall_name="Somebody Else", is_approved=True, is_open=True
        )
        db.add(other)
        await db.commit()
        await db.refresh(other)
        item = MenuItem(vendor_id=other.id, name="Their dish", price=Decimal("50.00"))
        db.add(item)
        await db.commit()
        await db.refresh(item)
        db.add(
            MenuItemVariant(
                item_id=item.id,
                name="Half",
                price=Decimal("30.00"),
                pending_price=Decimal("40.00"),
            )
        )
        await db.commit()

        body = (await client.get("/vendors/me/analytics", headers=headers)).json()
        assert body["pending_price_changes"] == 0

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


class TestWhereTheMoneyCameFrom:
    """Dine-in vs delivery, and cash vs prepaid.

    The rule worth pinning is the counter-intuitive one: a pay-on-delivery
    order settled by scanning the rider's QR counts as **prepaid**, not cash.
    It was placed as cash but it did not arrive as cash - Razorpay has it, it
    settles with every other online order, and it is not in the till. A stall
    counting its cash box against this screen would otherwise go looking for
    money that was never there.
    """

    async def _totals(self, client, vendor_headers):
        r = await client.get("/vendors/me/analytics", headers=vendor_headers)
        assert r.status_code == 200, r.text
        return r.json()["totals"]

    async def _cod_delivery(self, client, headers, vendor_id, item):
        r = await client.post(
            "/orders",
            headers=headers,
            json={
                "vendor_id": str(vendor_id),
                "items": _lines(item),
                "fulfilment_type": "delivery",
                "delivery_location": "hostel_3",
                "payment_method": "cod",
            },
        )
        assert r.status_code == 201, r.text
        return r.json()

    async def _to_the_door(self, client, order_id, vendor_headers):
        for status_value in ("accepted", "preparing", "ready", "out_for_delivery"):
            r = await client.patch(
                f"/vendors/me/orders/{order_id}/status",
                headers=vendor_headers,
                json={"status": status_value},
            )
            assert r.status_code == 200, r.text

    async def test_a_dine_in_prepaid_order_lands_in_both_right_slices(
        self, client, customer, vendor, menu_item, pay
    ):
        _, headers = customer
        v, vendor_headers = vendor
        await _paid_order(client, headers, v.id, menu_item, pay)

        totals = await self._totals(client, vendor_headers)
        assert totals["dine_in"]["orders"] == 1
        assert totals["delivery"]["orders"] == 0
        assert totals["prepaid"]["orders"] == 1
        assert totals["cash"]["orders"] == 0
        assert totals["dine_in"]["revenue"] == totals["revenue"]
        assert totals["prepaid"]["revenue"] == totals["revenue"]

    async def test_cash_taken_at_the_door_is_cash(
        self, client, customer, vendor, menu_item
    ):
        _, headers = customer
        v, vendor_headers = vendor
        order = await self._cod_delivery(client, headers, v.id, menu_item)
        await self._to_the_door(client, order["id"], vendor_headers)

        collected = await client.post(
            f"/vendors/me/orders/{order['id']}/collect",
            headers=vendor_headers,
            json={"method": "cash"},
        )
        assert collected.status_code == 200, collected.text

        totals = await self._totals(client, vendor_headers)
        assert totals["cash"]["orders"] == 1
        assert totals["prepaid"]["orders"] == 0
        assert totals["delivery"]["orders"] == 1
        assert totals["dine_in"]["orders"] == 0
        assert totals["cash"]["revenue"] == totals["revenue"]

    async def test_a_cod_order_paid_by_qr_counts_as_prepaid(
        self, stub_razorpay, signed_webhook, client, db, customer, vendor, menu_item
    ):
        """The whole point of this change.

        Placed as pay-on-delivery, settled by UPI at the door. The money is
        with Razorpay and the cash box is empty, so it belongs with the
        prepaid takings even though the order was never prepaid.
        """
        from decimal import Decimal as D

        from app.modules.payments import razorpay

        _, headers = customer
        v, vendor_headers = vendor
        order = await self._cod_delivery(client, headers, v.id, menu_item)
        await self._to_the_door(client, order["id"], vendor_headers)

        await client.post(
            f"/vendors/me/orders/{order['id']}/upi-qr", headers=vendor_headers
        )
        qr_id = stub_razorpay["qrs"][-1]["id"]

        credited = await signed_webhook(
            {
                "event": "qr_code.credited",
                "payload": {
                    "qr_code": {"entity": {"id": qr_id}},
                    "payment": {
                        "entity": {
                            "id": f"pay_{uuid.uuid4().hex[:12]}",
                            "status": "captured",
                            "amount": razorpay.to_paise(D(order["total_amount"])),
                            "currency": "INR",
                        }
                    },
                },
            }
        )
        assert credited.status_code == 200, credited.text
        assert credited.json()["status"] == "applied"

        totals = await self._totals(client, vendor_headers)
        assert totals["prepaid"]["orders"] == 1, "UPI at the door is not cash"
        assert totals["cash"]["orders"] == 0
        assert totals["cash"]["revenue"] == 0
        assert totals["prepaid"]["revenue"] == totals["revenue"]
        # And it is still a delivery, because the two splits are independent.
        assert totals["delivery"]["orders"] == 1

    async def test_each_pair_adds_up_to_the_takings(
        self, stub_razorpay, client, db, customer, vendor, menu_item, pay
    ):
        """A split whose parts do not sum to the whole is worse than none.

        Three orders of three different shapes, so both partitions have to
        reconcile against the same total rather than against one easy case.
        """
        _, headers = customer
        v, vendor_headers = vendor

        await _paid_order(client, headers, v.id, menu_item, pay)

        cash_order = await self._cod_delivery(client, headers, v.id, menu_item)
        await self._to_the_door(client, cash_order["id"], vendor_headers)
        await client.post(
            f"/vendors/me/orders/{cash_order['id']}/collect",
            headers=vendor_headers,
            json={"method": "cash"},
        )

        # And one left uncollected, which is in neither slice because it is not
        # revenue yet - nobody has been paid.
        owed = await self._cod_delivery(client, headers, v.id, menu_item)
        await self._to_the_door(client, owed["id"], vendor_headers)

        totals = await self._totals(client, vendor_headers)
        assert totals["dine_in"]["revenue"] + totals["delivery"]["revenue"] == pytest.approx(
            totals["revenue"]
        )
        assert totals["cash"]["revenue"] + totals["prepaid"]["revenue"] == pytest.approx(
            totals["revenue"]
        )
        # Three orders placed, two of them paid for.
        assert totals["orders"] == 3
        assert totals["dine_in"]["orders"] + totals["delivery"]["orders"] == 2

    async def test_the_slices_are_empty_rather_than_absent_on_a_quiet_day(
        self, client, vendor
    ):
        _, vendor_headers = vendor
        totals = await self._totals(client, vendor_headers)

        for slice_name in ("dine_in", "delivery", "cash", "prepaid"):
            assert totals[slice_name] == {"orders": 0, "revenue": 0.0}


class TestTheCrossTab:
    """The same money crossed both ways, and the two figures that are not it.

    The property that matters is arithmetic: every row and every column has to
    add up to the takings. A stall reads this against a cash box, and a table
    whose margins disagree with its cells is worse than no table.
    """

    async def _totals(self, client, vendor_headers):
        r = await client.get("/vendors/me/analytics", headers=vendor_headers)
        assert r.status_code == 200, r.text
        return r.json()["totals"]

    async def _cod_delivery(self, client, headers, vendor_id, item):
        r = await client.post(
            "/orders",
            headers=headers,
            json={
                "vendor_id": str(vendor_id),
                "items": _lines(item),
                "fulfilment_type": "delivery",
                "delivery_location": "hostel_3",
                "payment_method": "cod",
            },
        )
        assert r.status_code == 201, r.text
        return r.json()

    async def _to_the_door(self, client, order_id, vendor_headers):
        for status_value in ("accepted", "preparing", "ready", "out_for_delivery"):
            r = await client.patch(
                f"/vendors/me/orders/{order_id}/status",
                headers=vendor_headers,
                json={"status": status_value},
            )
            assert r.status_code == 200, r.text

    async def test_every_row_and_column_adds_up(
        self, client, db, customer, vendor, menu_item, pay
    ):
        _, headers = customer
        v, vendor_headers = vendor

        # One prepaid dine-in, one cash delivery, one uncollected cash delivery.
        await _paid_order(client, headers, v.id, menu_item, pay)

        cash_order = await self._cod_delivery(client, headers, v.id, menu_item)
        await self._to_the_door(client, cash_order["id"], vendor_headers)
        await client.post(
            f"/vendors/me/orders/{cash_order['id']}/collect",
            headers=vendor_headers,
            json={"method": "cash"},
        )

        owed_order = await self._cod_delivery(client, headers, v.id, menu_item)
        await self._to_the_door(client, owed_order["id"], vendor_headers)

        t = await self._totals(client, vendor_headers)

        def rev(name):
            return t[name]["revenue"]

        # Rows.
        assert rev("dine_in_prepaid") + rev("dine_in_cash") == pytest.approx(rev("dine_in"))
        assert rev("delivery_prepaid") + rev("delivery_cash") == pytest.approx(
            rev("delivery")
        )
        # Columns.
        assert rev("dine_in_prepaid") + rev("delivery_prepaid") == pytest.approx(
            rev("prepaid")
        )
        assert rev("dine_in_cash") + rev("delivery_cash") == pytest.approx(rev("cash"))
        # And the whole table against the corner.
        assert (
            rev("dine_in_prepaid")
            + rev("dine_in_cash")
            + rev("delivery_prepaid")
            + rev("delivery_cash")
        ) == pytest.approx(t["revenue"])

        # Order counts reconcile the same way, since they are what the cells
        # carry alongside the money.
        assert (
            t["dine_in_prepaid"]["orders"]
            + t["dine_in_cash"]["orders"]
            + t["delivery_prepaid"]["orders"]
            + t["delivery_cash"]["orders"]
        ) == t["dine_in"]["orders"] + t["delivery"]["orders"]

    async def test_the_cells_land_where_they_belong(
        self, client, db, customer, vendor, menu_item, pay
    ):
        _, headers = customer
        v, vendor_headers = vendor

        await _paid_order(client, headers, v.id, menu_item, pay)
        cash_order = await self._cod_delivery(client, headers, v.id, menu_item)
        await self._to_the_door(client, cash_order["id"], vendor_headers)
        await client.post(
            f"/vendors/me/orders/{cash_order['id']}/collect",
            headers=vendor_headers,
            json={"method": "cash"},
        )

        t = await self._totals(client, vendor_headers)

        assert t["dine_in_prepaid"]["orders"] == 1
        assert t["delivery_cash"]["orders"] == 1
        assert t["dine_in_cash"]["orders"] == 0
        assert t["delivery_prepaid"]["orders"] == 0

    async def test_dine_in_cash_is_structurally_empty(
        self, client, customer, vendor, menu_item
    ):
        """It is not that no dine-in order happened to be cash - it cannot be.

        OrderCreate.cash_is_for_deliveries refuses it, because there is nobody
        to collect from somebody standing at the counter. The cell is reported
        anyway so that a non-zero reading means a rule has been broken.
        """
        _, headers = customer
        v, vendor_headers = vendor

        refused = await client.post(
            "/orders",
            headers=headers,
            json={
                "vendor_id": str(v.id),
                "items": _lines(menu_item),
                "fulfilment_type": "dine_in",
                "payment_method": "cod",
            },
        )
        assert refused.status_code == 422, refused.text

        t = await self._totals(client, vendor_headers)
        assert t["dine_in_cash"] == {"orders": 0, "revenue": 0.0}

    async def test_money_owed_at_a_door_is_counted_but_not_as_takings(
        self, client, db, customer, vendor, menu_item
    ):
        """The stall's exposure, and the reason pay on delivery reversed a rule.

        Food is cooked and nobody has paid. It must not be revenue - nothing
        arrived - and it must not be invisible either.
        """
        _, headers = customer
        v, vendor_headers = vendor

        order = await self._cod_delivery(client, headers, v.id, menu_item)
        await self._to_the_door(client, order["id"], vendor_headers)

        t = await self._totals(client, vendor_headers)

        assert t["outstanding"]["orders"] == 1
        assert t["outstanding"]["revenue"] == pytest.approx(float(order["total_amount"]))
        assert t["revenue"] == 0, "nothing has been paid for"
        assert t["cash"]["revenue"] == 0
        assert t["prepaid"]["revenue"] == 0

    async def test_collecting_moves_it_out_of_owed_and_into_takings(
        self, client, db, customer, vendor, menu_item
    ):
        _, headers = customer
        v, vendor_headers = vendor

        order = await self._cod_delivery(client, headers, v.id, menu_item)
        await self._to_the_door(client, order["id"], vendor_headers)
        await client.post(
            f"/vendors/me/orders/{order['id']}/collect",
            headers=vendor_headers,
            json={"method": "cash"},
        )

        t = await self._totals(client, vendor_headers)

        assert t["outstanding"] == {"orders": 0, "revenue": 0.0}
        assert t["delivery_cash"]["orders"] == 1
        assert t["revenue"] == pytest.approx(float(order["total_amount"]))

    async def test_a_quiet_day_reports_empty_cells_rather_than_nothing(
        self, client, vendor
    ):
        _, vendor_headers = vendor
        t = await self._totals(client, vendor_headers)

        for name in (
            "dine_in_prepaid",
            "dine_in_cash",
            "delivery_prepaid",
            "delivery_cash",
            "outstanding",
            "refunded",
        ):
            assert t[name] == {"orders": 0, "revenue": 0.0}, name
