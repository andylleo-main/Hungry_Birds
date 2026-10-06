"""The smallest delivery a stall will cook for.

A ₹20 delivery costs a stall a trip across campus for almost nothing, so a stall
can now set a floor. Three things are worth pinning, and they are the three ways
this could quietly go wrong:

  * the floor is checked against the **server's** total, not the client's. It is
    asserted after every line has been priced off the rows the API read, which is
    also why it cannot live beside the mode and location checks that run before
    anything is priced;
  * **dine-in is exempt**, because there is no trip to the counter. A stall with a
    ₹100 delivery floor still sells one samosa to somebody standing in front of it;
  * the column's default is **₹100**, and that is not inert - every stall that
    existed before the migration starts refusing small deliveries the moment it
    runs. The suite's own fixture stall sets 0 explicitly so the rest of the tests
    are not affected, so the default is only observable here.
"""

import uuid
from decimal import Decimal

import pytest

pytest.importorskip("httpx")

from app.core.locations import DELIVERY_LOCATIONS  # noqa: E402


async def _stall(db, minimum=None, *, price="60.00"):
    """An approved stall with one dish, and optionally a minimum.

    Passing None leaves the column alone, which is the only way to see what the
    migration's server default actually does.
    """
    from app.core.security import TokenAudience
    from app.db.models.menu import MenuItem
    from app.db.models.user import User, UserRole
    from app.db.models.vendor import Vendor

    from tests.conftest import _token

    owner = User(email=f"floor.{uuid.uuid4().hex[:10]}@gmail.com", role=UserRole.VENDOR)
    db.add(owner)
    await db.commit()
    await db.refresh(owner)

    fields = {}
    if minimum is not None:
        fields["min_delivery_order"] = Decimal(minimum)
    stall = Vendor(
        user_id=owner.id,
        stall_name=f"Floor {uuid.uuid4().hex[:5]}",
        is_approved=True,
        is_open=True,
        **fields,
    )
    db.add(stall)
    await db.commit()
    await db.refresh(stall)

    item = MenuItem(
        vendor_id=stall.id, name="Momos", price=Decimal(price), is_available=True
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    return stall, item, _token(owner.id, TokenAudience.MERCHANT)


async def _order(client, headers, stall, item, quantity=1, *, delivery=True):
    body = {
        "vendor_id": str(stall.id),
        "items": [{"menu_item_id": str(item.id), "quantity": quantity}],
        "fulfilment_type": "delivery" if delivery else "dine_in",
    }
    if delivery:
        body["delivery_location"] = "hostel_5"
    return await client.post("/orders", headers=headers, json=body)


# --- the default ------------------------------------------------------------


async def test_a_stall_that_never_set_one_gets_a_hundred(db):
    """Straight off the column, with no application code involved.

    This is the test that proves the migration's server_default is what was
    asked for. Written against a freshly inserted row rather than through the
    API because the API has no way to *not* set a value, so nothing else in the
    suite can observe the default at all.
    """
    stall, _, _ = await _stall(db, None)
    assert stall.min_delivery_order == Decimal("100.00")


async def test_the_default_refuses_a_small_delivery_end_to_end(
    client, customer, db
):
    """The default is not decoration: it bites, through the real route."""
    _, headers = customer
    stall, item, _ = await _stall(db, None)

    r = await _order(client, headers, stall, item)

    assert r.status_code == 400, r.text
    assert "100" in r.json()["detail"]


# --- the boundary -----------------------------------------------------------


async def test_a_delivery_under_the_floor_is_refused(client, customer, db):
    _, headers = customer
    stall, item, _ = await _stall(db, "100.00")

    r = await _order(client, headers, stall, item)

    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    # The stall's own figure and the shortfall, because "too small" alone leaves
    # the customer guessing how much more to add.
    assert stall.stall_name in detail
    assert "₹100" in detail
    assert "₹40" in detail


async def test_exactly_the_floor_is_accepted(client, customer, db):
    """The boundary, and the reason the column is Numeric rather than a float.

    Two ₹60 dishes against a ₹120 floor is equal, not less - and a float would
    be free to disagree about that by a fraction of a paisa.
    """
    _, headers = customer
    stall, item, _ = await _stall(db, "120.00")

    r = await _order(client, headers, stall, item, quantity=2)

    assert r.status_code == 201, r.text
    assert Decimal(str(r.json()["total_amount"])) == Decimal("120.00")


async def test_a_rupee_over_is_accepted(client, customer, db):
    _, headers = customer
    stall, item, _ = await _stall(db, "119.00")

    r = await _order(client, headers, stall, item, quantity=2)

    assert r.status_code == 201, r.text


# --- what the floor does not apply to ---------------------------------------


async def test_dine_in_ignores_the_floor(client, customer, db):
    """There is nobody to send to somebody standing at the counter."""
    _, headers = customer
    stall, item, _ = await _stall(db, "100.00")

    r = await _order(client, headers, stall, item, delivery=False)

    assert r.status_code == 201, r.text


async def test_zero_means_no_minimum(client, customer, db):
    _, headers = customer
    stall, item, _ = await _stall(db, "0.00")

    r = await _order(client, headers, stall, item)

    assert r.status_code == 201, r.text


# --- the merchant editing it ------------------------------------------------


async def test_a_stall_can_read_and_change_its_floor(client, db):
    _, _, headers = await _stall(db, "100.00")

    before = await client.get("/vendors/me/fulfilment", headers=headers)
    assert before.status_code == 200, before.text
    assert Decimal(str(before.json()["min_delivery_order"])) == Decimal("100.00")

    saved = await client.put(
        "/vendors/me/fulfilment",
        headers=headers,
        json={
            "dine_in_enabled": True,
            "delivery_enabled": True,
            "enabled_locations": list(DELIVERY_LOCATIONS),
            "min_delivery_order": "250.00",
        },
    )

    assert saved.status_code == 200, saved.text
    assert Decimal(str(saved.json()["min_delivery_order"])) == Decimal("250.00")


async def test_omitting_the_field_leaves_the_floor_alone(client, db):
    """The released merchant APK does not send this field.

    It was built before the field existed, so a required field would mean an old
    app got a 422 trying to switch delivery off - a worse failure than not being
    able to edit a minimum it cannot display. So omission means "not editing
    this", not "set it to zero", and this is the test that keeps it that way.
    """
    _, _, headers = await _stall(db, "250.00")

    saved = await client.put(
        "/vendors/me/fulfilment",
        headers=headers,
        json={
            "dine_in_enabled": True,
            "delivery_enabled": False,
            "enabled_locations": [],
        },
    )

    assert saved.status_code == 200, saved.text
    assert Decimal(str(saved.json()["min_delivery_order"])) == Decimal("250.00")


@pytest.mark.parametrize("bad", ["-1", "10001", "not a number"])
async def test_a_nonsense_floor_is_refused(client, db, bad):
    """Negative is meaningless, and a huge one is a stall that silently takes no
    deliveries at all - which is what the delivery switch is for."""
    _, _, headers = await _stall(db, "100.00")

    r = await client.put(
        "/vendors/me/fulfilment",
        headers=headers,
        json={
            "dine_in_enabled": True,
            "delivery_enabled": True,
            "enabled_locations": list(DELIVERY_LOCATIONS),
            "min_delivery_order": bad,
        },
    )

    assert r.status_code == 422, r.text


# --- what the customer is shown ---------------------------------------------


async def test_the_floor_is_on_the_public_stall(client, customer, db):
    """So checkout can refuse a small basket before the customer submits it."""
    _, headers = customer
    stall, _, _ = await _stall(db, "150.00")

    r = await client.get(f"/vendors/{stall.id}", headers=headers)

    assert r.status_code == 200, r.text
    assert Decimal(str(r.json()["min_delivery_order"])) == Decimal("150.00")
