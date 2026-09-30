"""Riders: credentials, who may manage them, and what they can see.

The rules worth protecting here are that a rider's password is never readable
back out of the system, that regenerating one actually ends the old session, that
one stall cannot touch another's riders, and that a customer's phone number
reaches a rider only for an order that rider was given.
"""

import uuid

import pytest

pytest.importorskip("httpx")


async def test_creating_a_rider_shows_the_password_exactly_once(client, vendor):
    v, headers = vendor

    r = await client.post(
        "/vendors/me/riders",
        headers=headers,
        json={"display_name": "Amit Kumar", "phone": "09876512345"},
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["password"]
    assert created["login_id"].startswith("amit-")
    # The phone is normalised, so the customer's call button gets a dialable number.
    assert created["phone"] == "+919876512345"

    # And never again, in any later read.
    listed = await client.get("/vendors/me/riders", headers=headers)
    assert listed.status_code == 200
    assert [rr["id"] for rr in listed.json()] == [created["id"]]
    assert "password" not in listed.json()[0]


async def test_a_rider_signs_in_with_what_the_merchant_was_shown(client, rider):
    created, rider_headers = rider
    r = await client.get("/rider/me", headers=rider_headers)
    assert r.status_code == 200
    assert r.json()["login_id"] == created["login_id"]


async def test_a_wrong_password_and_an_unknown_id_look_identical(client, rider):
    created, _ = rider

    wrong = await client.post(
        "/auth/rider/login",
        json={"login_id": created["login_id"], "password": "swift-mango-0000"},
    )
    missing = await client.post(
        "/auth/rider/login",
        json={"login_id": "nobody-1234", "password": "swift-mango-0000"},
    )
    assert wrong.status_code == missing.status_code == 401
    # Same message, so probing cannot map which ids exist.
    assert wrong.json()["detail"] == missing.json()["detail"]


async def test_regenerating_a_password_signs_the_old_device_out(client, vendor, rider):
    v, vendor_headers = vendor
    created, rider_headers = rider

    # The old token works right now.
    assert (await client.get("/rider/me", headers=rider_headers)).status_code == 200

    r = await client.post(
        f"/vendors/me/riders/{created['id']}/password", headers=vendor_headers
    )
    assert r.status_code == 200, r.text
    fresh = r.json()["password"]
    assert fresh != created["password"]

    # The old one no longer does. This is the whole point of Regenerate: a rider
    # who has left must not keep a working token until it expires.
    stale = await client.get("/rider/me", headers=rider_headers)
    assert stale.status_code == 401
    assert "password was changed" in stale.json()["detail"]

    # And the new password signs in.
    again = await client.post(
        "/auth/rider/login",
        json={"login_id": created["login_id"], "password": fresh},
    )
    assert again.status_code == 200
    # The old password is dead too.
    old = await client.post(
        "/auth/rider/login",
        json={"login_id": created["login_id"], "password": created["password"]},
    )
    assert old.status_code == 401


async def test_deactivating_a_rider_ends_their_session_now(client, vendor, rider):
    v, vendor_headers = vendor
    created, rider_headers = rider

    r = await client.patch(
        f"/vendors/me/riders/{created['id']}",
        headers=vendor_headers,
        json={"is_active": False},
    )
    assert r.status_code == 200 and r.json()["is_active"] is False

    assert (await client.get("/rider/me", headers=rider_headers)).status_code == 401
    # And they cannot sign back in.
    back = await client.post(
        "/auth/rider/login",
        json={"login_id": created["login_id"], "password": created["password"]},
    )
    assert back.status_code == 401


async def test_a_chosen_login_id_that_is_taken_is_reported(client, vendor):
    v, headers = vendor
    wanted = f"kiran{uuid.uuid4().hex[:6]}"

    first = await client.post(
        "/vendors/me/riders",
        headers=headers,
        json={"display_name": "Kiran", "phone": "9876500022", "login_id": wanted},
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/vendors/me/riders",
        headers=headers,
        json={"display_name": "Kiran Two", "phone": "9876500033", "login_id": wanted},
    )
    assert second.status_code == 400
    assert "already taken" in second.json()["detail"]


async def test_a_rider_needs_a_real_phone_number(client, vendor):
    v, headers = vendor
    r = await client.post(
        "/vendors/me/riders",
        headers=headers,
        json={"display_name": "Nobody", "phone": "12345"},
    )
    assert r.status_code == 400
    assert "10-digit" in r.json()["detail"]


# --- one stall cannot reach another's riders --------------------------------


async def test_another_stall_cannot_see_or_change_your_riders(client, db, vendor, rider):
    """404 rather than 403, so ids cannot be mapped by probing."""
    from app.core.security import TokenAudience, create_access_token
    from app.db.models.user import User, UserRole
    from app.db.models.vendor import Vendor

    created, _ = rider

    other_user = User(email=f"other.{uuid.uuid4().hex[:8]}@gmail.com", role=UserRole.VENDOR)
    db.add(other_user)
    await db.commit()
    await db.refresh(other_user)
    other = Vendor(user_id=other_user.id, stall_name="Rival", is_approved=True, is_open=True)
    db.add(other)
    await db.commit()
    other_headers = {
        "Authorization": f"Bearer {create_access_token(str(other_user.id), TokenAudience.MERCHANT)}"
    }

    assert (await client.get("/vendors/me/riders", headers=other_headers)).json() == []

    r = await client.patch(
        f"/vendors/me/riders/{created['id']}", headers=other_headers, json={"display_name": "Mine"}
    )
    assert r.status_code == 404

    r = await client.post(
        f"/vendors/me/riders/{created['id']}/password", headers=other_headers
    )
    assert r.status_code == 404


async def test_a_customer_cannot_manage_riders(client, customer):
    user, headers = customer
    r = await client.get("/vendors/me/riders", headers=headers)
    assert r.status_code == 403
