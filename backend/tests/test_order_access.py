"""Who may see an order, and the two routes that have to agree about it.

There are two ways to reach an order - GET /orders/{id} and the order WebSocket -
and they each used to carry their own copy of the rule. They had drifted: the
socket let a stall subscribe to an order of theirs that nobody had paid for, which
the HTTP route refuses. Both now call may_view_order, and these tests pin the
answers so a future edit to one path cannot quietly re-create the split.
"""

import uuid

import pytest

pytest.importorskip("httpx")


def _lines(item, qty=1):
    return [{"menu_item_id": str(item.id), "quantity": qty}]


async def _place(client, headers, vendor_id, item, **extra):
    r = await client.post(
        "/orders",
        headers=headers,
        json={"vendor_id": str(vendor_id), "items": _lines(item), **extra},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_a_stall_cannot_see_an_order_nobody_has_paid_for(
    client, db, customer, vendor, menu_item
):
    """The rule itself. An unpaid order is the customer's alone - a stall that
    could see one might start cooking against money that never arrives."""
    from app.db.models.order import Order
    from app.db.models.user import User
    from app.modules.orders.service import may_view_order

    _, headers = customer
    v, _vendor_headers = vendor
    placed = await _place(client, headers, v.id, menu_item)

    order = await db.get(Order, uuid.UUID(placed["id"]))
    await db.refresh(order)
    owner = await db.get(User, v.user_id)

    assert order.status.value == "awaiting_payment"
    assert await may_view_order(order, owner, db) is False


async def test_the_customer_still_sees_their_own_unpaid_order(
    client, db, customer, vendor, menu_item
):
    """The other half: the tracking page has to be able to say "finish paying"."""
    from app.db.models.order import Order
    from app.modules.orders.service import may_view_order

    cust, headers = customer
    v, _ = vendor
    placed = await _place(client, headers, v.id, menu_item)

    order = await db.get(Order, uuid.UUID(placed["id"]))
    assert await may_view_order(order, cust, db) is True


async def test_an_unrelated_customer_sees_nothing(client, db, customer, vendor, menu_item):
    from app.core.security import TokenAudience, create_access_token  # noqa: F401
    from app.db.models.order import Order
    from app.db.models.user import User, UserRole
    from app.modules.orders.service import may_view_order

    _, headers = customer
    v, _ = vendor
    placed = await _place(client, headers, v.id, menu_item)
    order = await db.get(Order, uuid.UUID(placed["id"]))

    stranger = User(
        email=f"nosy.{uuid.uuid4().hex[:8]}@bitmesra.ac.in",
        role=UserRole.CUSTOMER,
        phone="+919812345678",
    )
    db.add(stranger)
    await db.commit()
    await db.refresh(stranger)

    assert await may_view_order(order, stranger, db) is False


async def test_the_http_route_and_the_socket_ask_the_same_question(client, customer, vendor, menu_item):
    """Both paths resolve to may_view_order, so neither can drift from the other.

    Checked by reading the source rather than by opening a socket: the point is
    that no second copy of the rule exists, and a behavioural test would still
    pass if someone reintroduced an identical-looking inline copy that later
    diverged - which is exactly what happened before.
    """
    from pathlib import Path

    realtime = Path("app/modules/realtime/router.py").read_text()
    orders = Path("app/modules/orders/router.py").read_text()

    assert "may_view_order" in realtime
    assert "may_view_order" in orders
    # The shape of the old inline copy. If this comes back, so has the bug.
    assert "is_owner_vendor" not in realtime
    assert "is_owner_vendor" not in orders
