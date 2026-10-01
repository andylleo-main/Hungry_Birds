"""Assigning a delivery, and the phone numbers that changes hands.

Assignment is what releases the customer's number to a rider and gives the
customer a number to call back. So the tests here are as much about who can see
a phone number as about who is carrying the food.
"""

import uuid

import pytest

pytest.importorskip("httpx")


async def _advance(client, headers, order_id, *statuses):
    for s in statuses:
        r = await client.patch(
            f"/vendors/me/orders/{order_id}/status", headers=headers, json={"status": s}
        )
        assert r.status_code == 200, (s, r.text)
    return r.json()


async def test_assigning_a_rider_exchanges_the_two_phone_numbers(
    client, customer, vendor, rider, delivery_order
):
    cust_user, cust_headers = customer
    v, vendor_headers = vendor
    created, rider_headers = rider

    # Before assignment the customer has nobody to call.
    before = await client.get(f"/orders/{delivery_order['id']}", headers=cust_headers)
    assert before.json()["rider_phone"] is None

    r = await client.post(
        f"/vendors/me/orders/{delivery_order['id']}/assign",
        headers=vendor_headers,
        json={"rider_id": created["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["rider_id"] == created["id"]
    assert r.json()["self_delivery"] is False

    # The customer can now call the rider.
    after = await client.get(f"/orders/{delivery_order['id']}", headers=cust_headers)
    assert after.json()["rider_name"] == "Ravi Kumar"
    assert after.json()["rider_phone"] == "+919876500011"

    # And the rider can call the customer.
    mine = await client.get("/rider/orders", headers=rider_headers)
    assert mine.status_code == 200, mine.text
    assert [o["id"] for o in mine.json()] == [delivery_order["id"]]
    assert mine.json()[0]["customer_phone"] == "+919876543210"
    assert mine.json()[0]["delivery_location_label"] == "Hostel 5"


async def test_a_rider_sees_nothing_they_were_not_given(
    client, vendor, rider, delivery_order
):
    """The order exists and is a delivery - it just is not theirs."""
    created, rider_headers = rider

    assert (await client.get("/rider/orders", headers=rider_headers)).json() == []

    r = await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "out_for_delivery"},
    )
    assert r.status_code == 404


async def test_the_merchant_can_take_a_delivery_themselves(
    client, vendor, rider, delivery_order
):
    v, vendor_headers = vendor
    created, rider_headers = rider

    # Assigned to a rider first, then taken back.
    await client.post(
        f"/vendors/me/orders/{delivery_order['id']}/assign",
        headers=vendor_headers,
        json={"rider_id": created["id"]},
    )
    r = await client.post(
        f"/vendors/me/orders/{delivery_order['id']}/assign",
        headers=vendor_headers,
        json={"self_delivery": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["self_delivery"] is True
    assert r.json()["rider_id"] is None
    assert r.json()["rider_phone"] is None

    # The rider no longer holds it.
    assert (await client.get("/rider/orders", headers=rider_headers)).json() == []


async def test_a_rider_and_self_delivery_are_mutually_exclusive(
    client, vendor, rider, delivery_order
):
    v, vendor_headers = vendor
    created, _ = rider
    r = await client.post(
        f"/vendors/me/orders/{delivery_order['id']}/assign",
        headers=vendor_headers,
        json={"rider_id": created["id"], "self_delivery": True},
    )
    assert r.status_code == 422


async def test_a_dine_in_order_has_nobody_to_assign(
    client, customer, vendor, rider, menu_item, pay
):
    cust_user, cust_headers = customer
    v, vendor_headers = vendor
    created, _ = rider

    r = await client.post(
        "/orders",
        headers=cust_headers,
        json={
            "vendor_id": str(v.id),
            "items": [{"menu_item_id": str(menu_item.id), "quantity": 1}],
            "fulfilment_type": "dine_in",
        },
    )
    order = r.json()
    await pay(order["id"])

    r = await client.post(
        f"/vendors/me/orders/{order['id']}/assign",
        headers=vendor_headers,
        json={"rider_id": created["id"]},
    )
    assert r.status_code == 400
    assert "delivery order" in r.json()["detail"]


async def test_a_stall_cannot_assign_another_stalls_rider(
    client, db, vendor, rider, delivery_order
):
    """The rider is real and the order is real; they belong to different stalls."""
    from app.core.security import TokenAudience, create_access_token
    from app.db.models.user import User, UserRole
    from app.db.models.vendor import Vendor

    created, _ = rider

    # A second stall, with its own order, trying to use the first stall's rider.
    other_user = User(email=f"rival.{uuid.uuid4().hex[:8]}@gmail.com", role=UserRole.VENDOR)
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)
    other = Vendor(user_id=other_user.id, stall_name="Rival", is_approved=True, is_open=True)
    db.add(other)
    await db.commit()

    v, vendor_headers = vendor
    r = await client.post(
        f"/vendors/me/orders/{delivery_order['id']}/assign",
        headers={
            "Authorization": f"Bearer {create_access_token(str(other_user.id), TokenAudience.MERCHANT)}"
        },
        json={"rider_id": created["id"]},
    )
    # Not their order, so it is not found at all.
    assert r.status_code == 404


async def test_an_inactive_rider_cannot_be_given_an_order(
    client, vendor, rider, delivery_order
):
    v, vendor_headers = vendor
    created, _ = rider

    await client.patch(
        f"/vendors/me/riders/{created['id']}", headers=vendor_headers, json={"is_active": False}
    )
    r = await client.post(
        f"/vendors/me/orders/{delivery_order['id']}/assign",
        headers=vendor_headers,
        json={"rider_id": created["id"]},
    )
    assert r.status_code == 400
    assert "no longer active" in r.json()["detail"]


# --- what a rider may change -------------------------------------------------


async def test_a_rider_marks_an_order_picked_up_then_delivered(
    client, vendor, rider, delivery_order
):
    v, vendor_headers = vendor
    created, rider_headers = rider

    await client.post(
        f"/vendors/me/orders/{delivery_order['id']}/assign",
        headers=vendor_headers,
        json={"rider_id": created["id"]},
    )
    await _advance(client, vendor_headers, delivery_order["id"], "accepted", "preparing", "ready")

    r = await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "out_for_delivery"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "out_for_delivery"

    r = await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "completed"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


async def test_a_rider_cannot_accept_or_reject_an_order(
    client, vendor, rider, delivery_order
):
    """Cooking decisions stay the stall's, whatever the transition table allows."""
    v, vendor_headers = vendor
    created, rider_headers = rider

    await client.post(
        f"/vendors/me/orders/{delivery_order['id']}/assign",
        headers=vendor_headers,
        json={"rider_id": created["id"]},
    )

    for bad in ("accepted", "rejected", "preparing", "cancelled"):
        r = await client.patch(
            f"/rider/orders/{delivery_order['id']}/status",
            headers=rider_headers,
            json={"status": bad},
        )
        assert r.status_code == 403, (bad, r.status_code)


async def test_out_for_delivery_is_refused_on_a_dine_in_order(
    client, customer, vendor, menu_item, pay
):
    cust_user, cust_headers = customer
    v, vendor_headers = vendor

    r = await client.post(
        "/orders",
        headers=cust_headers,
        json={
            "vendor_id": str(v.id),
            "items": [{"menu_item_id": str(menu_item.id), "quantity": 1}],
            "fulfilment_type": "dine_in",
        },
    )
    order = r.json()
    await pay(order["id"])
    await _advance(client, vendor_headers, order["id"], "accepted", "preparing", "ready")

    r = await client.patch(
        f"/vendors/me/orders/{order['id']}/status",
        headers=vendor_headers,
        json={"status": "out_for_delivery"},
    )
    assert r.status_code == 400
    assert "only applies to a delivery" in r.json()["detail"]


async def test_a_finished_order_cannot_be_reassigned(
    client, vendor, rider, delivery_order
):
    v, vendor_headers = vendor
    created, _ = rider

    await _advance(client, vendor_headers, delivery_order["id"], "accepted", "preparing", "ready")
    await _advance(client, vendor_headers, delivery_order["id"], "completed")

    r = await client.post(
        f"/vendors/me/orders/{delivery_order['id']}/assign",
        headers=vendor_headers,
        json={"rider_id": created["id"]},
    )
    assert r.status_code == 400
    assert "finished" in r.json()["detail"]
