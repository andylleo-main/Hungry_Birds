"""Dine-in, delivery, and the locations a stall will deliver to.

The rule being protected here is that a stall's own settings decide which orders
it can receive. Getting this wrong in either direction is bad: reject an order a
stall would happily have made, or accept a delivery to a building it has said it
does not go to and leave a rider to discover that.
"""

import uuid

import pytest

pytest.importorskip("httpx")

from app.core.locations import DELIVERY_LOCATIONS  # noqa: E402


def _lines(item):
    return [{"menu_item_id": str(item.id), "quantity": 1}]


async def test_defaults_to_every_location_enabled(client, vendor):
    """A stall that has never opened the settings screen delivers everywhere.

    This is the whole reason only the switched-off locations are stored: no
    seeding on vendor creation, and nothing to backfill for stalls that existed
    before delivery did.
    """
    v, headers = vendor
    r = await client.get("/vendors/me/fulfilment", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["dine_in_enabled"] is True
    assert body["delivery_enabled"] is True
    assert len(body["locations"]) == len(DELIVERY_LOCATIONS)
    assert all(loc["enabled"] for loc in body["locations"])
    # Labels come through, so the merchant app never renders a raw code.
    assert {"code": "ic_arena", "label": "IC Arena", "enabled": True} in body["locations"]


async def test_switching_locations_off_and_back_on(client, vendor):
    v, headers = vendor
    keep = [c for c in DELIVERY_LOCATIONS if c != "hostel_7"]

    r = await client.put(
        "/vendors/me/fulfilment",
        headers=headers,
        json={"dine_in_enabled": True, "delivery_enabled": True, "enabled_locations": keep},
    )
    assert r.status_code == 200, r.text
    off = [loc["code"] for loc in r.json()["locations"] if not loc["enabled"]]
    assert off == ["hostel_7"]

    # Re-enabling deletes the row rather than leaving a stale one behind.
    r = await client.put(
        "/vendors/me/fulfilment",
        headers=headers,
        json={
            "dine_in_enabled": True,
            "delivery_enabled": True,
            "enabled_locations": list(DELIVERY_LOCATIONS),
        },
    )
    assert r.status_code == 200
    assert all(loc["enabled"] for loc in r.json()["locations"])


async def test_cannot_switch_off_both_ways_of_getting_food(client, vendor):
    """A stall with neither mode reads as open but rejects everything."""
    v, headers = vendor
    r = await client.put(
        "/vendors/me/fulfilment",
        headers=headers,
        json={"dine_in_enabled": False, "delivery_enabled": False, "enabled_locations": []},
    )
    assert r.status_code == 400
    assert "close the stall" in r.json()["detail"].lower()


async def test_unknown_location_code_is_refused(client, vendor):
    v, headers = vendor
    r = await client.put(
        "/vendors/me/fulfilment",
        headers=headers,
        json={
            "dine_in_enabled": True,
            "delivery_enabled": True,
            "enabled_locations": ["hostel_1", "the_moon"],
        },
    )
    assert r.status_code == 400
    assert "the_moon" in r.json()["detail"]


async def test_delivery_order_to_an_enabled_location(client, customer, vendor, menu_item):
    user, headers = customer
    v, _ = vendor

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
    body = r.json()
    assert body["fulfilment_type"] == "delivery"
    assert body["delivery_location"] == "hostel_3"
    # The label is what the stall and the rider actually read.
    assert body["delivery_location_label"] == "Hostel 3"


async def test_delivery_to_a_switched_off_location_is_refused(
    client, customer, vendor, menu_item
):
    user, cust_headers = customer
    v, vendor_headers = vendor

    keep = [c for c in DELIVERY_LOCATIONS if c != "rnd_building"]
    r = await client.put(
        "/vendors/me/fulfilment",
        headers=vendor_headers,
        json={"dine_in_enabled": True, "delivery_enabled": True, "enabled_locations": keep},
    )
    assert r.status_code == 200

    r = await client.post(
        "/orders",
        headers=cust_headers,
        json={
            "vendor_id": str(v.id),
            "items": _lines(menu_item),
            "fulfilment_type": "delivery",
            "delivery_location": "rnd_building",
        },
    )
    assert r.status_code == 400
    assert "does not deliver" in r.json()["detail"]


async def test_dine_in_refused_when_the_stall_has_it_off(
    client, customer, vendor, menu_item
):
    user, cust_headers = customer
    v, vendor_headers = vendor

    r = await client.put(
        "/vendors/me/fulfilment",
        headers=vendor_headers,
        json={
            "dine_in_enabled": False,
            "delivery_enabled": True,
            "enabled_locations": list(DELIVERY_LOCATIONS),
        },
    )
    assert r.status_code == 200

    r = await client.post(
        "/orders",
        headers=cust_headers,
        json={"vendor_id": str(v.id), "items": _lines(menu_item), "fulfilment_type": "dine_in"},
    )
    assert r.status_code == 400
    assert "dine-in" in r.json()["detail"].lower()


async def test_delivery_refused_when_the_stall_has_it_off(
    client, customer, vendor, menu_item
):
    user, cust_headers = customer
    v, vendor_headers = vendor

    r = await client.put(
        "/vendors/me/fulfilment",
        headers=vendor_headers,
        json={
            "dine_in_enabled": True,
            "delivery_enabled": False,
            "enabled_locations": list(DELIVERY_LOCATIONS),
        },
    )
    assert r.status_code == 200

    r = await client.post(
        "/orders",
        headers=cust_headers,
        json={
            "vendor_id": str(v.id),
            "items": _lines(menu_item),
            "fulfilment_type": "delivery",
            "delivery_location": "hostel_1",
        },
    )
    assert r.status_code == 400
    assert "not delivering" in r.json()["detail"].lower()


async def test_an_unknown_location_on_an_order_is_refused(
    client, customer, vendor, menu_item
):
    """A stall with no disabled rows must not treat an unrecognised code as fine."""
    user, headers = customer
    v, _ = vendor

    r = await client.post(
        "/orders",
        headers=headers,
        json={
            "vendor_id": str(v.id),
            "items": _lines(menu_item),
            "fulfilment_type": "delivery",
            "delivery_location": "behind_the_bike_sheds",
        },
    )
    assert r.status_code == 400
    assert "unknown delivery location" in r.json()["detail"].lower()


async def test_shape_of_the_pair_is_validated(client, customer, vendor, menu_item):
    """A delivery needs a location; a dine-in must not smuggle one in."""
    user, headers = customer
    v, _ = vendor

    r = await client.post(
        "/orders",
        headers=headers,
        json={
            "vendor_id": str(v.id),
            "items": _lines(menu_item),
            "fulfilment_type": "delivery",
        },
    )
    assert r.status_code == 422

    r = await client.post(
        "/orders",
        headers=headers,
        json={
            "vendor_id": str(v.id),
            "items": _lines(menu_item),
            "fulfilment_type": "dine_in",
            "delivery_location": "hostel_2",
        },
    )
    assert r.status_code == 422


async def test_an_order_with_no_fulfilment_field_is_dine_in(
    client, customer, vendor, menu_item
):
    """A client that predates delivery keeps working."""
    user, headers = customer
    v, _ = vendor

    r = await client.post(
        "/orders",
        headers=headers,
        json={"vendor_id": str(v.id), "items": _lines(menu_item)},
    )
    assert r.status_code == 201, r.text
    assert r.json()["fulfilment_type"] == "dine_in"
    assert r.json()["delivery_location"] is None


async def test_customers_only_see_locations_the_stall_delivers_to(
    client, customer, vendor
):
    user, cust_headers = customer
    v, vendor_headers = vendor

    keep = ["hostel_1", "ic_arena"]
    r = await client.put(
        "/vendors/me/fulfilment",
        headers=vendor_headers,
        json={"dine_in_enabled": True, "delivery_enabled": True, "enabled_locations": keep},
    )
    assert r.status_code == 200

    r = await client.get(f"/vendors/{v.id}", headers=cust_headers)
    assert r.status_code == 200, r.text
    assert [loc["code"] for loc in r.json()["delivery_locations"]] == keep


async def test_a_stall_with_delivery_off_advertises_no_locations(client, customer, vendor):
    user, cust_headers = customer
    v, vendor_headers = vendor

    await client.put(
        "/vendors/me/fulfilment",
        headers=vendor_headers,
        json={
            "dine_in_enabled": True,
            "delivery_enabled": False,
            "enabled_locations": list(DELIVERY_LOCATIONS),
        },
    )

    r = await client.get(f"/vendors/{v.id}", headers=cust_headers)
    assert r.status_code == 200
    assert r.json()["delivery_locations"] == []
    assert r.json()["delivery_enabled"] is False
