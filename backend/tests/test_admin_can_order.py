"""An admin may buy food; a stall owner may not.

The ordering routes were CUSTOMER-only, which made the operator of the service the
one person who could not use it: roles are exclusive and immutable by design, an
address holding an admin account cannot also hold a customer one, and +tag
addressing is normalised away so a second account is not a workaround. The symptom
was a flat 403 from POST /orders with nothing to say why.

Both halves are pinned here. Widening a role check is exactly the kind of edit
that gets copied to the wrong place later, and the vendor half is the one that
would matter: a stall owner ordering from the platform they sell on is the
conflict the exclusive roles exist to prevent.
"""

import uuid

import pytest

pytest.importorskip("httpx")


@pytest.fixture
async def admin(db):
    """A signed-in admin on an institute address, as BOOTSTRAP_ADMIN_EMAIL makes."""
    from app.core.security import TokenAudience, create_access_token
    from app.db.models.user import User, UserRole

    user = User(
        email=f"admin.{uuid.uuid4().hex[:10]}@bitmesra.ac.in",
        role=UserRole.ADMIN,
        full_name="The Operator",
        phone="+919876500000",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, {"Authorization": f"Bearer {create_access_token(str(user.id), TokenAudience.WEB)}"}


def _lines(item, qty=1):
    return [{"menu_item_id": str(item.id), "quantity": qty}]


async def test_an_admin_can_place_an_order(client, admin, vendor, menu_item):
    _, headers = admin
    v, _ = vendor

    r = await client.post(
        "/orders",
        headers=headers,
        json={"vendor_id": str(v.id), "items": _lines(menu_item)},
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "awaiting_payment"


async def test_an_admin_can_pay_for_it(client, admin, vendor, menu_item, mock_payments):
    """The whole point - the 403 was killing checkout before payment was reached."""
    _, headers = admin
    v, _ = vendor

    order = (
        await client.post(
            "/orders",
            headers=headers,
            json={"vendor_id": str(v.id), "items": _lines(menu_item)},
        )
    ).json()

    session = await client.post(f"/orders/{order['id']}/payment-session", headers=headers)
    assert session.status_code == 200, session.text
    assert session.json()["mode"] == "mock"

    paid = await client.post(f"/orders/{order['id']}/mock-payment", headers=headers)
    assert paid.status_code == 200, paid.text
    assert paid.json()["status"] == "applied"

    after = (await client.get(f"/orders/{order['id']}", headers=headers)).json()
    assert after["payment_status"] == "paid"
    assert after["status"] == "placed"


async def test_an_admin_sees_their_own_orders_in_the_customer_list(
    client, admin, vendor, menu_item
):
    _, headers = admin
    v, _ = vendor
    order = (
        await client.post(
            "/orders",
            headers=headers,
            json={"vendor_id": str(v.id), "items": _lines(menu_item)},
        )
    ).json()

    mine = await client.get("/orders", headers=headers)
    assert mine.status_code == 200, mine.text
    assert order["id"] in [o["id"] for o in mine.json()]


async def test_a_stall_owner_still_cannot_order(client, vendor, menu_item):
    """The half that must not move. A vendor buying on the platform they sell on
    is the conflict exclusive roles exist to prevent."""
    v, vendor_headers = vendor

    r = await client.post(
        "/orders",
        headers=vendor_headers,
        json={"vendor_id": str(v.id), "items": _lines(menu_item)},
    )
    assert r.status_code in (401, 403), r.text
