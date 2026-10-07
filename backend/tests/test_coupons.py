"""Discount codes: a use taken twice, or never given back.

A coupon is simple until two people try the last one at the same moment, or a
stall refuses the order that was holding it. Most of what follows is about those
two, because everything else about a coupon is a multiplication.

The lifecycle is the same one cashback has - held at placement, consumed on
completion, returned on a refusal - so the tests that matter are the same shape
too, and a few of them exist specifically to catch the two promotions drifting
apart.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

pytest.importorskip("httpx")

from app.db.models.coupon import (  # noqa: E402
    Coupon,
    CouponAudience,
    CouponRedemption,
    DiscountType,
    ExpiryType,
)
from app.modules.coupons.service import worth_on  # noqa: E402


# --- the arithmetic ---------------------------------------------------------


def coupon(**kw) -> Coupon:
    """A coupon object with no database behind it, for the pure functions."""
    fields = {
        "code": "TEST",
        "discount_type": DiscountType.PERCENT,
        "discount_value": Decimal("10"),
        "max_discount": None,
        "expiry_type": ExpiryType.COUNT,
        "max_uses": 100,
        "min_order_value": Decimal("0"),
        "audience": CouponAudience.ANYONE,
        "is_active": True,
        "one_per_customer": True,
        "show_in_offers": False,
    }
    fields.update(kw)
    return Coupon(**fields)


class TestWhatACouponIsWorth:
    def test_a_percentage_of_the_cart(self):
        assert worth_on(coupon(discount_value=Decimal("10")), Decimal("200")) == Decimal("20")

    def test_a_flat_amount_ignores_the_cart(self):
        c = coupon(discount_type=DiscountType.FLAT, discount_value=Decimal("100"))
        assert worth_on(c, Decimal("500")) == Decimal("100")

    def test_max_discount_caps_a_percentage(self):
        c = coupon(discount_value=Decimal("50"), max_discount=Decimal("40"))
        assert worth_on(c, Decimal("200")) == Decimal("40")

    def test_max_discount_is_ignored_on_a_flat_coupon(self):
        """"₹100 off, up to ₹50" is a contradiction, not a qualifier.

        Honouring the smaller number would mean an admin's ₹100 code quietly
        paying out ₹50, which is the sort of thing nobody notices for a month.
        """
        c = coupon(
            discount_type=DiscountType.FLAT,
            discount_value=Decimal("100"),
            max_discount=Decimal("50"),
        )
        assert worth_on(c, Decimal("500")) == Decimal("100")

    def test_rounding_is_always_down(self):
        c = coupon(discount_value=Decimal("10"))
        assert worth_on(c, Decimal("99")) == Decimal("9")

    def test_it_can_never_take_an_order_to_zero(self):
        """The property the payment path depends on.

        A ₹0 order would need a ₹0 Razorpay order, which the gateway will not
        open. Checked across a range rather than at one point, because this is a
        claim about the function rather than about an example.
        """
        full = coupon(discount_value=Decimal("100"))
        flat = coupon(discount_type=DiscountType.FLAT, discount_value=Decimal("9999"))
        for cart in (2, 7, 50, 199, 1000, 9999):
            for c in (full, flat):
                assert Decimal(cart) - worth_on(c, Decimal(cart)) >= Decimal("1"), cart

    def test_a_cart_too_small_to_discount_is_worth_nothing(self):
        assert worth_on(coupon(discount_value=Decimal("100")), Decimal("1")) == Decimal("0")


# --- end to end -------------------------------------------------------------


async def _stall(db, name="Coupon Stall", price="200.00"):
    from app.core.security import TokenAudience
    from app.db.models.menu import MenuItem
    from app.db.models.user import User, UserRole
    from app.db.models.vendor import Vendor

    from tests.conftest import _token

    owner = User(email=f"cp.{uuid.uuid4().hex[:10]}@gmail.com", role=UserRole.VENDOR)
    db.add(owner)
    await db.commit()
    await db.refresh(owner)
    stall = Vendor(
        user_id=owner.id,
        stall_name=name,
        is_approved=True,
        is_open=True,
        min_delivery_order=Decimal("0.00"),
    )
    db.add(stall)
    await db.commit()
    await db.refresh(stall)
    item = MenuItem(
        vendor_id=stall.id, name="Thali", price=Decimal(price), is_available=True
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return stall, item, _token(owner.id, TokenAudience.MERCHANT)


async def _coupon(db, **kw):
    now = datetime.now(timezone.utc)
    fields = {
        "code": f"SAVE{uuid.uuid4().hex[:6].upper()}",
        "discount_type": DiscountType.FLAT,
        "discount_value": Decimal("50.00"),
        "expiry_type": ExpiryType.COUNT,
        "max_uses": 100,
        "min_order_value": Decimal("0.00"),
        "audience": CouponAudience.ANYONE,
        "is_active": True,
        "one_per_customer": True,
        "show_in_offers": False,
        "created_at": now,
        "updated_at": now,
    }
    fields.update(kw)
    row = Coupon(**fields)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _place(client, headers, stall, item, code=None, **kw):
    body = {
        "vendor_id": str(stall.id),
        "items": [{"menu_item_id": str(item.id), "quantity": kw.get("quantity", 1)}],
        "fulfilment_type": "dine_in",
    }
    if code is not None:
        body["coupon_code"] = code
    if kw.get("redeem"):
        body["redeem_cashback"] = True
    return await client.post("/orders", headers=headers, json=body)


async def _finish(client, vendor_headers, order_id):
    for step in ("accepted", "preparing", "ready", "completed"):
        r = await client.patch(
            f"/vendors/me/orders/{order_id}/status",
            headers=vendor_headers,
            json={"status": step},
        )
        assert r.status_code == 200, (step, r.text)


async def _states(db, coupon_id):
    from sqlalchemy import select

    rows = await db.execute(
        select(CouponRedemption.state).where(CouponRedemption.coupon_id == coupon_id)
    )
    return sorted(s.value for s in rows.scalars())


class TestApplyingACode:
    async def test_it_comes_off_what_is_owed_not_off_the_stall(
        self, client, customer, db
    ):
        """The same decision cashback made: Hungry Birds funds the discount, so
        total_amount keeps saying what the stall is owed for the food."""
        _, headers = customer
        stall, item, _ = await _stall(db)
        code = (await _coupon(db)).code

        placed = await _place(client, headers, stall, item, code=code)

        assert placed.status_code == 201, placed.text
        body = placed.json()
        assert Decimal(body["total_amount"]) == Decimal("200.00")
        assert Decimal(body["coupon_discount"]) == Decimal("50.00")
        assert Decimal(body["amount_due"]) == Decimal("150.00")

    async def test_the_code_is_matched_however_it_is_typed(self, client, customer, db):
        _, headers = customer
        stall, item, _ = await _stall(db)
        # Unique per run - the code column is unique, and the suite can be
        # pointed at a database that already has rows - while still being typed
        # back in the wrong case and with stray spaces, which is the point.
        code = f"WELCOME{uuid.uuid4().hex[:6].upper()}"
        c = await _coupon(db, code=code)

        placed = await _place(client, headers, stall, item, code=f"  {code.lower()} ")

        assert placed.status_code == 201, placed.text
        assert Decimal(placed.json()["coupon_discount"]) == Decimal("50.00")
        assert await _states(db, c.id) == ["held"]

    async def test_an_unknown_code_fails_the_order(self, client, customer, db):
        """Rather than quietly placing it at full price.

        Somebody who typed a code expects it to count, and an order that ignored
        it is a refund conversation.
        """
        _, headers = customer
        stall, item, _ = await _stall(db)

        placed = await _place(client, headers, stall, item, code="NOPE")

        assert placed.status_code == 400, placed.text
        assert "code" in placed.json()["detail"].lower()

    async def test_a_use_is_held_not_yet_consumed(self, client, customer, db):
        """Held counts against the limit immediately - that is what stops two
        checkouts taking the last one - but says nothing has been earned."""
        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(db)

        await _place(client, headers, stall, item, code=c.code)

        assert await _states(db, c.id) == ["held"]

    async def test_completing_the_order_consumes_it(self, client, customer, db, pay):
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        c = await _coupon(db)
        order = (await _place(client, headers, stall, item, code=c.code)).json()
        await pay(order["id"])

        await _finish(client, vendor_headers, order["id"])

        assert await _states(db, c.id) == ["consumed"]


class TestTheLimits:
    async def test_a_one_use_code_cannot_be_taken_twice(self, client, customer, db):
        from app.core.security import TokenAudience
        from app.db.models.user import User, UserRole

        from tests.conftest import INSTITUTE, _token

        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(db, max_uses=1)

        first = await _place(client, headers, stall, item, code=c.code)
        assert first.status_code == 201, first.text

        # A different student, so the per-customer rule is not what refuses it.
        other = User(
            email=f"two.{uuid.uuid4().hex[:8]}@{INSTITUTE}",
            role=UserRole.CUSTOMER,
            full_name="Second Student",
            phone="+919876500022",
        )
        db.add(other)
        await db.commit()
        await db.refresh(other)

        second = await _place(
            client, headers=_token(other.id, TokenAudience.WEB), stall=stall, item=item, code=c.code
        )

        assert second.status_code == 400, second.text
        assert "claimed" in second.json()["detail"]

    async def test_one_use_per_customer_refuses_the_same_student(
        self, client, customer, db
    ):
        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(db, max_uses=100, one_per_customer=True)

        assert (await _place(client, headers, stall, item, code=c.code)).status_code == 201
        again = await _place(client, headers, stall, item, code=c.code)

        assert again.status_code == 400, again.text
        assert "already used" in again.json()["detail"]

    async def test_a_coupon_may_allow_repeat_use(self, client, customer, db):
        """The case a unique index on (coupon, customer) would have broken.

        There is deliberately no such index - a partial unique index cannot read
        the coupon's own flag to find out whether it applies - and this is the
        test that would have caught it.
        """
        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(db, max_uses=100, one_per_customer=False)

        assert (await _place(client, headers, stall, item, code=c.code)).status_code == 201
        again = await _place(client, headers, stall, item, code=c.code)

        assert again.status_code == 201, again.text
        assert await _states(db, c.id) == ["held", "held"]

    async def test_an_expired_date_is_refused(self, client, customer, db):
        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(
            db,
            expiry_type=ExpiryType.DATE,
            max_uses=None,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        placed = await _place(client, headers, stall, item, code=c.code)

        assert placed.status_code == 400
        assert "expired" in placed.json()["detail"]

    async def test_a_future_date_is_fine(self, client, customer, db):
        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(
            db,
            expiry_type=ExpiryType.DATE,
            max_uses=None,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )

        assert (await _place(client, headers, stall, item, code=c.code)).status_code == 201

    async def test_an_inactive_code_is_refused(self, client, customer, db):
        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(db, is_active=False)

        placed = await _place(client, headers, stall, item, code=c.code)

        assert placed.status_code == 400
        assert "active" in placed.json()["detail"]

    async def test_below_the_minimum_order_value_it_is_refused_with_the_shortfall(
        self, client, customer, db
    ):
        _, headers = customer
        stall, item, _ = await _stall(db, price="100.00")
        c = await _coupon(db, min_order_value=Decimal("150.00"))

        placed = await _place(client, headers, stall, item, code=c.code)

        assert placed.status_code == 400
        detail = placed.json()["detail"]
        assert "₹150" in detail and "₹50" in detail

    async def test_a_stall_pinned_code_does_not_work_elsewhere(
        self, client, customer, db
    ):
        _, headers = customer
        mine, my_item, _ = await _stall(db, name="Mine")
        theirs, _, _ = await _stall(db, name="Theirs")
        c = await _coupon(db, vendor_id=theirs.id)

        placed = await _place(client, headers, mine, my_item, code=c.code)

        assert placed.status_code == 400
        assert "this stall" in placed.json()["detail"]
        # Deliberately does not name the stall it is for.
        assert "Theirs" not in placed.json()["detail"]

    async def test_a_stall_pinned_code_works_at_its_own_stall(
        self, client, customer, db
    ):
        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(db, vendor_id=stall.id)

        assert (await _place(client, headers, stall, item, code=c.code)).status_code == 201


class TestWhoCanUseIt:
    async def test_a_first_order_code_works_for_a_new_student(
        self, client, customer, db
    ):
        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(db, audience=CouponAudience.FIRST_ORDER)

        assert (await _place(client, headers, stall, item, code=c.code)).status_code == 201

    async def test_and_is_refused_once_they_have_been_served(
        self, client, customer, db, pay
    ):
        """Completed, not placed. An order that was rejected or abandoned leaves
        a student still never served, which is who the code is for."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        first = (await _place(client, headers, stall, item)).json()
        await pay(first["id"])
        await _finish(client, vendor_headers, first["id"])

        c = await _coupon(db, audience=CouponAudience.FIRST_ORDER)
        placed = await _place(client, headers, stall, item, code=c.code)

        assert placed.status_code == 400
        assert "first order" in placed.json()["detail"]

    async def test_a_named_code_works_for_a_listed_address(self, client, customer, db):
        from app.db.models.coupon import CouponAudienceMember

        user, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(db, audience=CouponAudience.NAMED)
        db.add(CouponAudienceMember(coupon_id=c.id, email=user.email.lower()))
        await db.commit()

        assert (await _place(client, headers, stall, item, code=c.code)).status_code == 201

    async def test_and_is_refused_for_anybody_else(self, client, customer, db):
        from app.db.models.coupon import CouponAudienceMember

        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(db, audience=CouponAudience.NAMED)
        db.add(CouponAudienceMember(coupon_id=c.id, email="somebody.else@example.com"))
        await db.commit()

        placed = await _place(client, headers, stall, item, code=c.code)

        assert placed.status_code == 400
        assert "different account" in placed.json()["detail"]


class TestARefusedOrderGivesTheUseBack:
    async def test_rejecting_hands_it_back(self, client, customer, db, pay):
        """Without this a refused order burns a one-use code on food nobody got."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        c = await _coupon(db, max_uses=1)
        order = (await _place(client, headers, stall, item, code=c.code)).json()
        await pay(order["id"])

        r = await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "rejected"},
        )
        assert r.status_code == 200, r.text

        assert await _states(db, c.id) == ["returned"]

    async def test_and_the_code_works_again_afterwards(self, client, customer, db, pay):
        """The point of handing it back, asserted rather than assumed."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        c = await _coupon(db, max_uses=1, one_per_customer=False)
        order = (await _place(client, headers, stall, item, code=c.code)).json()
        await pay(order["id"])
        await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "rejected"},
        )

        again = await _place(client, headers, stall, item, code=c.code)

        assert again.status_code == 201, again.text

    async def test_cancelling_hands_it_back_too(self, client, customer, db, pay):
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        c = await _coupon(db)
        order = (await _place(client, headers, stall, item, code=c.code)).json()
        await pay(order["id"])
        await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "cancelled"},
        )

        assert await _states(db, c.id) == ["returned"]

    async def test_handing_back_twice_returns_one_use(self, client, customer, db, pay):
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        c = await _coupon(db, max_uses=1)
        order = (await _place(client, headers, stall, item, code=c.code)).json()
        await pay(order["id"])
        for _ in range(3):
            await client.patch(
                f"/vendors/me/orders/{order['id']}/status",
                headers=vendor_headers,
                json={"status": "rejected"},
            )

        assert await _states(db, c.id) == ["returned"]

    async def test_a_completed_order_keeps_its_use(self, client, customer, db, pay):
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        c = await _coupon(db)
        order = (await _place(client, headers, stall, item, code=c.code)).json()
        await pay(order["id"])
        await _finish(client, vendor_headers, order["id"])

        assert await _states(db, c.id) == ["consumed"]


class TestOnePromotionAtATime:
    async def test_a_coupon_and_cashback_together_are_refused(
        self, client, customer, db
    ):
        """By the server, not only by the checkout page.

        Either silent choice would be wrong for somebody: dropping the coupon
        charges more than the screen said, and dropping the cashback spends a
        balance they did not mean to spend.
        """
        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(db)

        placed = await _place(client, headers, stall, item, code=c.code, redeem=True)

        assert placed.status_code == 422, placed.text

    async def test_an_order_with_a_coupon_earns_no_cashback(
        self, client, customer, db, pay, cashback_on
    ):
        """The rule Phase 2 wrote and left waiting for this column.

        It was `getattr(order, "coupon_discount", 0)` specifically so that adding
        the column would be the whole change. This is the test that it was.
        """
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        c = await _coupon(db)
        order = (await _place(client, headers, stall, item, code=c.code)).json()
        await pay(order["id"])
        await _finish(client, vendor_headers, order["id"])

        wallets = (await client.get("/cashback", headers=headers)).json()["wallets"]
        assert all(Decimal(str(w["balance"])) == 0 for w in wallets)

    async def test_an_order_without_one_still_earns(
        self, client, customer, db, pay, cashback_on
    ):
        """The control, so the test above is not passing for the wrong reason."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        order = (await _place(client, headers, stall, item)).json()
        await pay(order["id"])
        await _finish(client, vendor_headers, order["id"])

        wallets = (await client.get("/cashback", headers=headers)).json()["wallets"]
        normal = next(w for w in wallets if w["kind"] == "normal")
        assert Decimal(str(normal["balance"])) == Decimal("40")


class TestTwoPeopleAtOnce:
    async def test_a_one_use_code_cannot_be_held_by_two_sessions(self, db):
        """The reason hold_onto takes `SELECT … FOR UPDATE` on the coupon.

        Checking the limit and writing the use are two statements. Without the
        lock both transactions read "nothing claimed yet" before either writes,
        and a one-use code pays out twice.

        Driven through two **real, separate database sessions** rather than two
        HTTP requests. Requests through ASGITransport do not reliably overlap, so
        a test built on them passes whether or not the lock is there - which is
        worse than no test. Two sessions on the same engine genuinely contend:
        the second blocks on the first's row lock, and only re-reads the count
        once the first has committed.
        """
        import asyncio

        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.core.config import get_settings
        from app.core.security import TokenAudience  # noqa: F401
        from app.db.models.order import FulfilmentType, Order, OrderStatus
        from app.db.models.user import User, UserRole
        from app.modules.coupons import service

        from tests.conftest import INSTITUTE

        stall, item, _ = await _stall(db)
        c = await _coupon(db, max_uses=1, one_per_customer=False)

        students = []
        for n in range(2):
            u = User(
                email=f"race{n}.{uuid.uuid4().hex[:8]}@{INSTITUTE}",
                role=UserRole.CUSTOMER,
                full_name=f"Racer {n}",
                phone=f"+91987651{n:04d}",
            )
            db.add(u)
            students.append(u)
        await db.commit()
        for u in students:
            await db.refresh(u)

        # A bare order row each, standing in for the one place_order builds.
        orders = []
        for n, u in enumerate(students):
            o = Order(
                customer_id=u.id,
                vendor_id=stall.id,
                total_amount=Decimal("200.00"),
                # Unique per run: the suite can be pointed at a database that
                # already has rows, and a fixed number collides on the second go.
                order_number=f"{uuid.uuid4().int % 1000000:06d}-{n:04d}",
                fulfilment_type=FulfilmentType.DINE_IN,
                status=OrderStatus.AWAITING_PAYMENT,
            )
            db.add(o)
            orders.append(o)
        await db.commit()
        for o in orders:
            await db.refresh(o)

        engine = create_async_engine(get_settings().database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def attempt(order_id, user_id):
            """One checkout, in its own transaction, committing at the end."""
            async with factory() as session:
                order = await session.get(Order, order_id)
                user = await session.get(User, user_id)
                try:
                    await service.hold_onto(
                        order, user, c.code, Decimal("200.00"), session
                    )
                    await session.commit()
                    return "won"
                except service.CouponError as exc:
                    await session.rollback()
                    return exc.message

        try:
            outcomes = await asyncio.gather(
                attempt(orders[0].id, students[0].id),
                attempt(orders[1].id, students[1].id),
            )
        finally:
            await engine.dispose()

        assert outcomes.count("won") == 1, outcomes
        assert any("claimed" in o for o in outcomes if o != "won"), outcomes
        assert await _states(db, c.id) == ["held"]


# --- the endpoints ----------------------------------------------------------


@pytest.fixture
async def admin(db):
    """A signed-in admin, as BOOTSTRAP_ADMIN_EMAIL makes one."""
    from app.core.security import TokenAudience, create_access_token
    from app.db.models.user import User, UserRole

    user = User(
        email=f"cpadmin.{uuid.uuid4().hex[:10]}@bitmesra.ac.in",
        role=UserRole.ADMIN,
        full_name="The Operator",
        phone="+919876500000",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, {
        "Authorization": f"Bearer {create_access_token(str(user.id), TokenAudience.WEB)}"
    }


def _form(**kw):
    """The admin form's payload, with the fields the screenshots show."""
    body = {
        "code": f"ADMIN{uuid.uuid4().hex[:6].upper()}",
        "discount_type": "percent",
        "discount_value": "10.00",
        "expiry_type": "count",
        "max_uses": 100,
        "min_order_value": "0.00",
        "audience": "anyone",
        "is_active": True,
        "one_per_customer": True,
        "show_in_offers": False,
    }
    body.update(kw)
    return body


class TestCheckingACodeBeforeOrdering:
    async def test_it_says_what_the_code_is_worth(self, client, customer, db):
        _, headers = customer
        stall, _, _ = await _stall(db)
        c = await _coupon(db, discount_type=DiscountType.PERCENT, discount_value=Decimal("25"))

        r = await client.post(
            "/coupons/check",
            headers=headers,
            json={"code": c.code, "vendor_id": str(stall.id), "subtotal": "200.00"},
        )

        assert r.status_code == 200, r.text
        assert Decimal(str(r.json()["discount"])) == Decimal("50")

    async def test_it_agrees_with_what_the_order_actually_applies(
        self, client, customer, db
    ):
        """The reason the endpoint exists rather than the browser doing the sum.

        A student shown one figure and charged against another stops trusting the
        app, and never reports it as a bug.
        """
        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(
            db, discount_type=DiscountType.PERCENT, discount_value=Decimal("15")
        )

        quoted = await client.post(
            "/coupons/check",
            headers=headers,
            json={"code": c.code, "vendor_id": str(stall.id), "subtotal": "200.00"},
        )
        placed = await _place(client, headers, stall, item, code=c.code)

        assert Decimal(str(quoted.json()["discount"])) == Decimal(
            placed.json()["coupon_discount"]
        )

    async def test_a_refusal_comes_back_in_words(self, client, customer, db):
        _, headers = customer
        stall, _, _ = await _stall(db)
        c = await _coupon(db, audience=CouponAudience.FIRST_ORDER, is_active=False)

        r = await client.post(
            "/coupons/check",
            headers=headers,
            json={"code": c.code, "vendor_id": str(stall.id), "subtotal": "200.00"},
        )

        assert r.status_code == 400
        assert "active" in r.json()["detail"]

    async def test_checking_reserves_nothing(self, client, customer, db):
        """A preview that held a use would be a way to exhaust a code with a
        loop and no orders."""
        _, headers = customer
        stall, _, _ = await _stall(db)
        c = await _coupon(db, max_uses=1)

        for _ in range(3):
            await client.post(
                "/coupons/check",
                headers=headers,
                json={"code": c.code, "vendor_id": str(stall.id), "subtotal": "200.00"},
            )

        assert await _states(db, c.id) == []

    async def test_signing_in_is_required(self, client, db):
        stall, _, _ = await _stall(db)
        r = await client.post(
            "/coupons/check",
            json={"code": "ANY", "vendor_id": str(stall.id), "subtotal": "10.00"},
        )
        assert r.status_code == 401


class TestWhatAStudentIsOffered:
    async def test_only_codes_marked_to_show(self, client, customer, db):
        _, headers = customer
        stall, _, _ = await _stall(db)
        shown = await _coupon(db, show_in_offers=True)
        await _coupon(db, show_in_offers=False)

        r = await client.get(
            "/coupons/available", headers=headers, params={"subtotal": "200.00"}
        )

        assert r.status_code == 200, r.text
        # Membership rather than the whole list: other tests share this database
        # and leave their own offerable coupons behind.
        codes = [c["code"] for c in r.json()]
        assert shown.code in codes

    async def test_an_automatic_code_is_offered_even_unticked(
        self, client, customer, db
    ):
        """It has no code to type, so leaving it out would make it invisible
        until it applied itself."""
        _, headers = customer
        await _stall(db)
        auto = await _coupon(db, audience=CouponAudience.AUTOMATIC, show_in_offers=False)

        r = await client.get(
            "/coupons/available", headers=headers, params={"subtotal": "200.00"}
        )

        offered = {c["code"]: c for c in r.json()}
        assert auto.code in offered
        assert offered[auto.code]["automatic"] is True

    async def test_a_code_this_student_cannot_use_is_not_offered(
        self, client, customer, db, pay
    ):
        """Eligibility is decided by the same function the order path runs, so a
        code can never be advertised here and refused at checkout."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        order = (await _place(client, headers, stall, item)).json()
        await pay(order["id"])
        await _finish(client, vendor_headers, order["id"])

        gone = await _coupon(
            db, audience=CouponAudience.FIRST_ORDER, show_in_offers=True
        )

        r = await client.get(
            "/coupons/available", headers=headers, params={"subtotal": "200.00"}
        )

        assert gone.code not in [c["code"] for c in r.json()]

    async def test_without_a_stall_only_site_wide_codes_are_offered(
        self, client, customer, db
    ):
        """A stall-pinned code cannot be judged without knowing which stall, so
        the offers page - which has no cart - does not list them."""
        _, headers = customer
        stall, _, _ = await _stall(db)
        everywhere = await _coupon(db, show_in_offers=True)
        pinned = await _coupon(db, show_in_offers=True, vendor_id=stall.id)

        r = await client.get(
            "/coupons/available", headers=headers, params={"subtotal": "200.00"}
        )

        codes = [c["code"] for c in r.json()]
        assert everywhere.code in codes
        assert pinned.code not in codes

    async def test_the_best_one_comes_first(self, client, customer, db):
        _, headers = customer
        await _stall(db)
        small = await _coupon(db, show_in_offers=True, discount_value=Decimal("20.00"))
        big = await _coupon(db, show_in_offers=True, discount_value=Decimal("90.00"))

        r = await client.get(
            "/coupons/available", headers=headers, params={"subtotal": "200.00"}
        )

        # Relative order of this test's own two, since the list also carries
        # whatever other tests left behind.
        codes = [c["code"] for c in r.json()]
        assert codes.index(big.code) < codes.index(small.code)


class TestTheAdminDesk:
    async def test_a_coupon_can_be_made_and_listed(self, client, admin):
        _, headers = admin
        body = _form()

        made = await client.post("/admin/coupons", headers=headers, json=body)
        assert made.status_code == 201, made.text
        assert made.json()["code"] == body["code"]
        assert made.json()["uses"] == 0

        listed = await client.get("/admin/coupons", headers=headers)
        assert body["code"] in [c["code"] for c in listed.json()]

    async def test_the_code_is_stored_upper_cased(self, client, admin):
        _, headers = admin
        # Unique per run, since the code column is unique and the suite can be
        # pointed at a database that already has rows.
        typed = f"lower{uuid.uuid4().hex[:6]}"
        made = await client.post("/admin/coupons", headers=headers, json=_form(code=typed))
        assert made.status_code == 201, made.text
        assert made.json()["code"] == typed.upper()

    async def test_a_duplicate_code_is_refused_in_words(self, client, admin):
        _, headers = admin
        body = _form()
        await client.post("/admin/coupons", headers=headers, json=body)

        again = await client.post("/admin/coupons", headers=headers, json=body)

        assert again.status_code == 409, again.text
        assert body["code"] in again.json()["detail"]

    async def test_a_count_coupon_without_a_count_is_refused(self, client, admin):
        """Both silent defaults are bad: an uncapped code is money, and one that
        expires immediately is a support ticket."""
        _, headers = admin
        r = await client.post(
            "/admin/coupons", headers=headers, json=_form(max_uses=None)
        )
        assert r.status_code == 422

    async def test_a_dated_coupon_without_a_date_is_refused(self, client, admin):
        _, headers = admin
        r = await client.post(
            "/admin/coupons",
            headers=headers,
            json=_form(expiry_type="date", max_uses=None, expires_at=None),
        )
        assert r.status_code == 422

    async def test_more_than_a_hundred_percent_is_refused(self, client, admin):
        _, headers = admin
        r = await client.post(
            "/admin/coupons", headers=headers, json=_form(discount_value="120.00")
        )
        assert r.status_code == 422

    async def test_a_named_coupon_with_nobody_named_is_refused(self, client, admin):
        _, headers = admin
        r = await client.post(
            "/admin/coupons",
            headers=headers,
            json=_form(audience="named", audience_emails=[]),
        )
        assert r.status_code == 422

    async def test_editing_keeps_the_uses_it_already_had(
        self, client, admin, customer, db
    ):
        """What a student was given does not change because the poster did."""
        _, admin_headers = admin
        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(db, discount_value=Decimal("50.00"))
        await _place(client, headers, stall, item, code=c.code)

        edited = await client.put(
            f"/admin/coupons/{c.id}",
            headers=admin_headers,
            json=_form(code=c.code, discount_type="flat", discount_value="10.00"),
        )

        assert edited.status_code == 200, edited.text
        assert edited.json()["uses"] == 1
        assert await _states(db, c.id) == ["held"]

    async def test_switching_to_a_count_clears_the_old_date(self, client, admin):
        """So a coupon does not keep a date that nothing reads."""
        _, headers = admin
        made = (
            await client.post(
                "/admin/coupons",
                headers=headers,
                json=_form(
                    expiry_type="date",
                    max_uses=None,
                    expires_at="2030-01-01T00:00:00Z",
                ),
            )
        ).json()

        edited = await client.put(
            f"/admin/coupons/{made['id']}",
            headers=headers,
            json=_form(code=made["code"], expiry_type="count", max_uses=5),
        )

        assert edited.json()["expires_at"] is None
        assert edited.json()["max_uses"] == 5

    async def test_a_flat_coupon_does_not_keep_a_max_discount(self, client, admin):
        _, headers = admin
        made = await client.post(
            "/admin/coupons",
            headers=headers,
            json=_form(discount_type="flat", discount_value="100.00", max_discount="50.00"),
        )
        assert made.json()["max_discount"] is None

    async def test_the_uses_figure_counts_held_and_consumed_but_not_returned(
        self, client, admin, customer, db, pay
    ):
        """Derived from the rows every time, so it cannot drift from them - which
        is why there is no "recount" button to repair it."""
        _, admin_headers = admin
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        c = await _coupon(db, max_uses=10, one_per_customer=False)

        kept = (await _place(client, headers, stall, item, code=c.code)).json()
        await pay(kept["id"])
        await _finish(client, vendor_headers, kept["id"])

        refused = (await _place(client, headers, stall, item, code=c.code)).json()
        await pay(refused["id"])
        await client.patch(
            f"/vendors/me/orders/{refused['id']}/status",
            headers=vendor_headers,
            json={"status": "rejected"},
        )

        listed = (await client.get("/admin/coupons", headers=admin_headers)).json()
        row = next(x for x in listed if x["code"] == c.code)
        assert row["uses"] == 1

    async def test_a_customer_cannot_reach_the_admin_desk(self, client, customer):
        _, headers = customer
        assert (await client.get("/admin/coupons", headers=headers)).status_code == 403
        assert (
            await client.post("/admin/coupons", headers=headers, json=_form())
        ).status_code == 403

    async def test_signing_in_is_required(self, client):
        assert (await client.get("/admin/coupons")).status_code == 401


class TestTheRedemptionsLog:
    async def test_it_shows_who_used_what(self, client, admin, customer, db):
        user, headers = customer
        _, admin_headers = admin
        stall, item, _ = await _stall(db)
        c = await _coupon(db)
        order = (await _place(client, headers, stall, item, code=c.code)).json()

        log = (await client.get("/admin/coupons/redemptions", headers=admin_headers)).json()

        row = next(r for r in log if r["code"] == c.code)
        assert row["customer_email"] == user.email
        assert row["order_number"] == order["order_number"]
        assert row["state"] == "held"
        assert Decimal(str(row["discount"])) == Decimal("50.00")

    async def test_handing_one_back_returns_the_use(
        self, client, admin, customer, db
    ):
        """The same function a refused order calls, so the manual path and the
        automatic one cannot drift apart."""
        _, headers = customer
        _, admin_headers = admin
        stall, item, _ = await _stall(db)
        c = await _coupon(db, max_uses=1)
        await _place(client, headers, stall, item, code=c.code)

        log = (await client.get("/admin/coupons/redemptions", headers=admin_headers)).json()
        row = next(r for r in log if r["code"] == c.code)

        done = await client.post(
            f"/admin/coupons/redemptions/{row['id']}/hand-back", headers=admin_headers
        )

        assert done.status_code == 200, done.text
        assert done.json()["state"] == "returned"
        assert await _states(db, c.id) == ["returned"]

    async def test_handing_the_same_one_back_twice_is_refused(
        self, client, admin, customer, db
    ):
        _, headers = customer
        _, admin_headers = admin
        stall, item, _ = await _stall(db)
        c = await _coupon(db)
        await _place(client, headers, stall, item, code=c.code)
        log = (await client.get("/admin/coupons/redemptions", headers=admin_headers)).json()
        row = next(r for r in log if r["code"] == c.code)
        await client.post(
            f"/admin/coupons/redemptions/{row['id']}/hand-back", headers=admin_headers
        )

        again = await client.post(
            f"/admin/coupons/redemptions/{row['id']}/hand-back", headers=admin_headers
        )

        assert again.status_code == 400
        assert "already" in again.json()["detail"]
        # And still only one use returned, not two.
        assert await _states(db, c.id) == ["returned"]

    async def test_a_consumed_use_can_still_be_handed_back(
        self, client, admin, customer, db, pay
    ):
        """For the cases the status machine cannot know about - an order that
        went wrong in a way nothing models."""
        _, headers = customer
        _, admin_headers = admin
        stall, item, vendor_headers = await _stall(db)
        c = await _coupon(db)
        order = (await _place(client, headers, stall, item, code=c.code)).json()
        await pay(order["id"])
        await _finish(client, vendor_headers, order["id"])

        log = (await client.get("/admin/coupons/redemptions", headers=admin_headers)).json()
        row = next(r for r in log if r["code"] == c.code)
        assert row["state"] == "consumed"

        done = await client.post(
            f"/admin/coupons/redemptions/{row['id']}/hand-back", headers=admin_headers
        )

        assert done.status_code == 200, done.text
        assert await _states(db, c.id) == ["returned"]

    async def test_a_customer_cannot_hand_anything_back(self, client, customer, db):
        _, headers = customer
        r = await client.post(
            f"/admin/coupons/redemptions/{uuid.uuid4()}/hand-back", headers=headers
        )
        assert r.status_code == 403


class TestCleaningUp:
    async def test_it_deletes_coupons_whose_date_has_passed(self, client, admin, db):
        _, headers = admin
        stale = await _coupon(
            db,
            expiry_type=ExpiryType.DATE,
            max_uses=None,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        fresh = await _coupon(
            db,
            expiry_type=ExpiryType.DATE,
            max_uses=None,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )

        r = await client.post("/admin/coupons/cleanup-expired", headers=headers)

        assert r.status_code == 200, r.text
        assert r.json()["deleted"] >= 1
        codes = [c["code"] for c in (await client.get("/admin/coupons", headers=headers)).json()]
        assert stale.code not in codes
        assert fresh.code in codes

    async def test_a_fully_claimed_count_coupon_is_left_alone(
        self, client, admin, customer, db
    ):
        """Not expired in the same sense: it may be worth raising the limit on,
        and its log is the record of a promotion that worked."""
        _, admin_headers = admin
        _, headers = customer
        stall, item, _ = await _stall(db)
        c = await _coupon(db, max_uses=1)
        await _place(client, headers, stall, item, code=c.code)

        await client.post("/admin/coupons/cleanup-expired", headers=admin_headers)

        codes = [
            x["code"] for x in (await client.get("/admin/coupons", headers=admin_headers)).json()
        ]
        assert c.code in codes
