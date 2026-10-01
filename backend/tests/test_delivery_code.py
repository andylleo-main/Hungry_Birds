"""The handover code: proof a delivery actually reached the customer.

Without it, "delivered" is a button a rider can press from the stall doorway and
the customer's only recourse is arguing about it afterwards. The rules that make
it worth anything are that the rider never sees the code, cannot guess it, and
cannot close a delivery without it - while the stall keeps a way to finish an
order when the code is lost.
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


async def _assigned(client, vendor_headers, rider, order_id):
    created, rider_headers = rider
    r = await client.post(
        f"/vendors/me/orders/{order_id}/assign",
        headers=vendor_headers,
        json={"rider_id": created["id"]},
    )
    assert r.status_code == 200, r.text
    return rider_headers


# --- who can see it ---------------------------------------------------------


async def test_a_delivery_gets_a_code_and_the_customer_can_see_it(
    client, customer, delivery_order
):
    user, cust_headers = customer
    assert delivery_order["delivery_code"]
    assert len(delivery_order["delivery_code"]) == 4
    assert delivery_order["delivery_code"].isdigit()

    fresh = await client.get(f"/orders/{delivery_order['id']}", headers=cust_headers)
    assert fresh.json()["delivery_code"] == delivery_order["delivery_code"]


async def test_the_stall_can_read_the_code_back_to_a_customer(
    client, vendor, delivery_order
):
    """For the phone that died on the way to the gate."""
    v, vendor_headers = vendor
    queue = await client.get("/vendors/me/orders", headers=vendor_headers)
    mine = next(o for o in queue.json() if o["id"] == delivery_order["id"])
    assert mine["delivery_code"] == delivery_order["delivery_code"]


async def test_the_rider_is_never_shown_the_code(
    client, vendor, rider, delivery_order
):
    """The single rule the whole feature rests on."""
    v, vendor_headers = vendor
    rider_headers = await _assigned(client, vendor_headers, rider, delivery_order["id"])

    mine = await client.get("/rider/orders", headers=rider_headers)
    assert mine.status_code == 200
    order = mine.json()[0]
    assert order["id"] == delivery_order["id"]
    # Not null - absent. A null would still tell a rider a code exists; this
    # payload has no such field at all.
    assert "delivery_code" not in order


async def test_a_dine_in_order_has_no_code_to_give(
    client, customer, vendor, menu_item, pay
):
    """Nothing changes hands away from the counter, so there is nothing to prove."""
    user, cust_headers = customer
    v, _ = vendor
    r = await client.post(
        "/orders",
        headers=cust_headers,
        json={
            "vendor_id": str(v.id),
            "items": [{"menu_item_id": str(menu_item.id), "quantity": 1}],
            "fulfilment_type": "dine_in",
        },
    )
    assert r.status_code == 201
    assert r.json()["delivery_code"] is None


# --- using it ---------------------------------------------------------------


async def test_the_right_code_completes_the_delivery(
    client, vendor, rider, delivery_order
):
    v, vendor_headers = vendor
    rider_headers = await _assigned(client, vendor_headers, rider, delivery_order["id"])
    await _advance(client, vendor_headers, delivery_order["id"], "accepted", "preparing", "ready")
    await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "out_for_delivery"},
    )

    r = await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "completed", "delivery_code": delivery_order["delivery_code"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"


async def test_a_rider_cannot_close_a_delivery_without_the_code(
    client, vendor, rider, delivery_order
):
    v, vendor_headers = vendor
    rider_headers = await _assigned(client, vendor_headers, rider, delivery_order["id"])
    await _advance(client, vendor_headers, delivery_order["id"], "accepted", "preparing", "ready")
    await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "out_for_delivery"},
    )

    r = await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "completed"},
    )
    assert r.status_code == 400
    assert "4-digit code" in r.json()["detail"]


async def test_a_wrong_code_is_refused(client, vendor, rider, delivery_order):
    v, vendor_headers = vendor
    rider_headers = await _assigned(client, vendor_headers, rider, delivery_order["id"])
    await _advance(client, vendor_headers, delivery_order["id"], "accepted", "preparing", "ready")
    await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "out_for_delivery"},
    )

    wrong = "0000" if delivery_order["delivery_code"] != "0000" else "1111"
    r = await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "completed", "delivery_code": wrong},
    )
    assert r.status_code == 400
    assert "does not match" in r.json()["detail"]

    # And the order is still out for delivery, not quietly closed.
    user_view = await client.get("/rider/orders", headers=rider_headers)
    assert user_view.json()[0]["status"] == "out_for_delivery"


async def test_guessing_is_cut_off_after_a_few_tries(
    client, vendor, rider, delivery_order
):
    """Four digits is only hopeless to guess if guessing is bounded."""
    v, vendor_headers = vendor
    rider_headers = await _assigned(client, vendor_headers, rider, delivery_order["id"])
    await _advance(client, vendor_headers, delivery_order["id"], "accepted", "preparing", "ready")
    await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "out_for_delivery"},
    )

    real = delivery_order["delivery_code"]
    wrongs = [f"{n:04d}" for n in range(9000, 9020) if f"{n:04d}" != real]

    statuses = []
    for code in wrongs[:8]:
        r = await client.patch(
            f"/rider/orders/{delivery_order['id']}/status",
            headers=rider_headers,
            json={"status": "completed", "delivery_code": code},
        )
        statuses.append(r.status_code)

    assert 429 in statuses, f"guessing was never cut off: {statuses}"

    # Even the correct code is refused once the limit is hit - the stall has to
    # step in, so a human decides whether the food actually arrived.
    r = await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "completed", "delivery_code": real},
    )
    assert r.status_code == 429


async def test_the_stall_can_still_finish_an_order_when_the_code_is_lost(
    client, vendor, rider, delivery_order
):
    """The escape hatch, and the reason locking a rider out is safe."""
    v, vendor_headers = vendor
    rider_headers = await _assigned(client, vendor_headers, rider, delivery_order["id"])
    await _advance(client, vendor_headers, delivery_order["id"], "accepted", "preparing", "ready")
    await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "out_for_delivery"},
    )

    r = await client.patch(
        f"/vendors/me/orders/{delivery_order['id']}/status",
        headers=vendor_headers,
        json={"status": "completed"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"


async def test_picking_an_order_up_needs_no_code(client, vendor, rider, delivery_order):
    """There is nothing to prove until it reaches somebody."""
    v, vendor_headers = vendor
    rider_headers = await _assigned(client, vendor_headers, rider, delivery_order["id"])
    await _advance(client, vendor_headers, delivery_order["id"], "accepted", "preparing", "ready")

    r = await client.patch(
        f"/rider/orders/{delivery_order['id']}/status",
        headers=rider_headers,
        json={"status": "out_for_delivery"},
    )
    assert r.status_code == 200, r.text
