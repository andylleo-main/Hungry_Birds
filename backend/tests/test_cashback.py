"""Promotional cashback: the money this feature creates, and where it must not.

This is the first thing in the project that mints value rather than moving value
somebody already owed, so most of what follows is about money that should *not*
exist: a credit on an order nobody paid for, a credit counted twice because two
routes can finish the same delivery, a balance that survives its own expiry, a
redemption a refused order quietly keeps.

The arithmetic is tested as pure functions first. The balance walk in particular
is worth pinning in isolation, because the bug it exists to prevent - a naive sum
going *negative* once a spent credit expires - is invisible until a student has
both spent and waited.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

pytest.importorskip("httpx")

from app.db.models.cashback import (  # noqa: E402
    CashbackEntry,
    CashbackKind,
    CashbackReason,
)
from app.modules.cashback.service import (  # noqa: E402
    Rate,
    earned_on,
    live_balances,
    next_expiry,
    spendable_on,
)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
NORMAL = Rate(20, Decimal("40"))
GOURMET = Rate(60, Decimal("90"))


def entry(
    amount,
    *,
    kind=CashbackKind.NORMAL,
    reason=CashbackReason.EARNED,
    at=NOW,
    expires=None,
):
    """A ledger row, without a database. The walk only reads these five fields."""
    return CashbackEntry(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        kind=kind,
        amount=Decimal(amount),
        reason=reason,
        order_id=None,
        expires_at=expires,
        created_at=at,
    )


# --- the arithmetic ---------------------------------------------------------


class TestWhatAnOrderEarns:
    def test_a_percentage_of_the_cart(self):
        assert earned_on(Decimal("150.00"), NORMAL) == Decimal("30")

    def test_the_cap_binds_before_the_percentage_does(self):
        """A ₹500 cart at 20% is ₹100, and the cap says ₹40.

        The cap is the whole reason the rate is not just a multiplication, and
        getting this backwards would cost two and a half times what was budgeted
        on exactly the orders that are worth the most.
        """
        assert earned_on(Decimal("500.00"), NORMAL) == Decimal("40")

    def test_gourmet_earns_more_and_caps_higher(self):
        assert earned_on(Decimal("100.00"), GOURMET) == Decimal("60")
        assert earned_on(Decimal("500.00"), GOURMET) == Decimal("90")

    def test_rounding_is_always_down(self):
        """₹99 at 20% is ₹19.80, and nobody hands over 80 paise.

        Down rather than nearest, so a cap can never pay out more than the
        setting says. The most a student loses is under a rupee, off a discount
        they are being given.
        """
        assert earned_on(Decimal("99.00"), NORMAL) == Decimal("19")

    def test_nothing_from_nothing(self):
        assert earned_on(Decimal("0"), NORMAL) == Decimal("0")
        assert earned_on(Decimal("150"), Rate(0, Decimal("40"))) == Decimal("0")


class TestWhatCanBeSpent:
    def test_the_share_of_the_cart(self):
        assert spendable_on(Decimal("200"), Decimal("500"), NORMAL) == Decimal("40")

    def test_the_balance_when_it_is_smaller(self):
        assert spendable_on(Decimal("200"), Decimal("15"), NORMAL) == Decimal("15")

    def test_gourmet_can_spend_most_of_a_cart(self):
        assert spendable_on(Decimal("200"), Decimal("500"), GOURMET) == Decimal("120")

    def test_it_can_never_cover_the_whole_cart(self):
        """The property that means amount_due is never zero.

        No redemption at any cart size or balance reaches 100%, which is why
        there is no free order to handle and no zero-rupee gateway call to
        special-case. Checked across a range rather than at one point, because
        this is a claim about the function rather than about an example.
        """
        for cart in (1, 7, 50, 199, 1000, 9999):
            for rate in (NORMAL, GOURMET):
                spend = spendable_on(Decimal(cart), Decimal("100000"), rate)
                assert spend < Decimal(cart), (cart, rate)

    def test_an_empty_wallet_spends_nothing(self):
        assert spendable_on(Decimal("200"), Decimal("0"), NORMAL) == Decimal("0")


class TestTheBalanceIsAWalkNotASum:
    def test_credits_add_up(self):
        entries = [entry("40", expires=NOW + timedelta(days=30)), entry("10")]
        assert live_balances(entries, NOW)[CashbackKind.NORMAL] == Decimal("50")

    def test_a_redemption_comes_off(self):
        entries = [
            entry("40", expires=NOW + timedelta(days=30)),
            entry("-15", reason=CashbackReason.REDEEMED, at=NOW + timedelta(hours=1)),
        ]
        assert live_balances(entries, NOW + timedelta(hours=2))[
            CashbackKind.NORMAL
        ] == Decimal("25")

    def test_an_expired_credit_is_gone(self):
        entries = [entry("40", expires=NOW + timedelta(days=1))]
        assert live_balances(entries, NOW + timedelta(days=2))[
            CashbackKind.NORMAL
        ] == Decimal("0")

    def test_a_spent_credit_that_later_expires_does_not_go_negative(self):
        """The bug this whole design exists to avoid.

        ₹40 earned, expiring in a day. Spent in full while it was alive. A sum of
        unexpired credits two days later is ₹0, and adding the ₹40 debit gives
        *minus* ₹40 - a balance that would then eat the next credit the student
        earned. Only a walk knows the debit consumed a credit that has since
        expired.
        """
        entries = [
            entry("40", expires=NOW + timedelta(days=1)),
            entry("-40", reason=CashbackReason.REDEEMED, at=NOW + timedelta(hours=2)),
        ]
        assert live_balances(entries, NOW + timedelta(days=2))[
            CashbackKind.NORMAL
        ] == Decimal("0")

    def test_the_soonest_expiring_credit_is_spent_first(self):
        """So the student keeps the most usable balance.

        ₹20 expiring tomorrow and ₹20 expiring next month; spend ₹20. Take the
        wrong one and the remaining ₹20 dies overnight; take the right one and
        the student still has ₹20 a week later.
        """
        entries = [
            entry("20", expires=NOW + timedelta(days=30)),
            entry("20", expires=NOW + timedelta(days=1), at=NOW + timedelta(minutes=1)),
            entry("-20", reason=CashbackReason.REDEEMED, at=NOW + timedelta(minutes=2)),
        ]
        assert live_balances(entries, NOW + timedelta(days=7))[
            CashbackKind.NORMAL
        ] == Decimal("20")

    def test_a_credit_already_expired_when_spent_is_not_consumed(self):
        """A debit can only eat what was alive when it happened.

        Otherwise a redemption made today could reach back and consume a credit
        that expired last week, and the live credit it should have taken would
        survive - inflating the balance.
        """
        entries = [
            entry("40", expires=NOW + timedelta(days=1)),
            entry("40", expires=NOW + timedelta(days=60), at=NOW + timedelta(days=2)),
            entry("-40", reason=CashbackReason.REDEEMED, at=NOW + timedelta(days=3)),
        ]
        assert live_balances(entries, NOW + timedelta(days=4))[
            CashbackKind.NORMAL
        ] == Decimal("0")

    def test_the_two_wallets_never_mix(self):
        entries = [
            entry("40", kind=CashbackKind.NORMAL, expires=NOW + timedelta(days=30)),
            entry("90", kind=CashbackKind.GOURMET, expires=NOW + timedelta(days=30)),
            entry(
                "-40",
                kind=CashbackKind.GOURMET,
                reason=CashbackReason.REDEEMED,
                at=NOW + timedelta(hours=1),
            ),
        ]
        live = live_balances(entries, NOW + timedelta(hours=2))
        assert live[CashbackKind.NORMAL] == Decimal("40")
        assert live[CashbackKind.GOURMET] == Decimal("50")

    def test_a_credit_with_no_expiry_lives_forever(self):
        """CASHBACK_EXPIRY_DAYS of 0 is a usable way to turn expiry off."""
        entries = [entry("40", expires=None)]
        assert live_balances(entries, NOW + timedelta(days=4000))[
            CashbackKind.NORMAL
        ] == Decimal("40")

    def test_an_inconsistent_ledger_clamps_at_zero_rather_than_raising(self, caplog):
        """A debit with nothing behind it should be impossible.

        Redemptions are written in the same transaction as the discount they pay
        for, so this means a bug or a hand repair. It is logged and clamped
        because this function is on every read path: a balance of zero is a
        better answer to "something is inconsistent" than an offers page that
        will not render.
        """
        entries = [entry("-40", reason=CashbackReason.REDEEMED)]
        with caplog.at_level("WARNING"):
            live = live_balances(entries, NOW)
        assert live[CashbackKind.NORMAL] == Decimal("0")
        assert "inconsistent" in caplog.text

    def test_a_returned_redemption_is_spendable_again(self):
        entries = [
            entry("40", expires=NOW + timedelta(days=30)),
            entry("-40", reason=CashbackReason.REDEEMED, at=NOW + timedelta(hours=1)),
            entry(
                "40",
                reason=CashbackReason.RETURNED,
                at=NOW + timedelta(hours=2),
                expires=NOW + timedelta(days=30),
            ),
        ]
        assert live_balances(entries, NOW + timedelta(hours=3))[
            CashbackKind.NORMAL
        ] == Decimal("40")


class TestNextExpiry:
    def test_the_soonest_unexpired_credit(self):
        soon = NOW + timedelta(days=2)
        entries = [
            entry("40", expires=NOW + timedelta(days=30)),
            entry("10", expires=soon),
        ]
        assert next_expiry(entries, CashbackKind.NORMAL, NOW) == soon

    def test_one_already_gone_is_not_offered(self):
        entries = [entry("40", expires=NOW - timedelta(days=1))]
        assert next_expiry(entries, CashbackKind.NORMAL, NOW) is None

    def test_nothing_to_say_about_an_empty_wallet(self):
        assert next_expiry([], CashbackKind.GOURMET, NOW) is None


# --- end to end -------------------------------------------------------------
#
# From here on it is the real app over ASGI, because the parts worth doubting are
# the wiring rather than the sums: which route credits, which transaction it
# commits in, and what a refusal undoes.


@pytest.fixture
def cashback_on(client):
    """Flat 20/60 with a named Gourmet stall, for one test.

    The suite's default settings leave GOURMET_KITCHEN_NAME empty - the safe
    production default, where the expensive tier simply does not exist - so a
    test that wants the 60% tier has to name it.
    """
    from app.core.config import get_settings
    from app.main import app

    from tests.conftest import _test_settings

    configured = _test_settings().model_copy(
        update={
            "gourmet_kitchen_name": "Gourmet Kitchen",
            "cashback_normal_percent": 20,
            "cashback_normal_cap": Decimal("40"),
            "cashback_gourmet_percent": 60,
            "cashback_gourmet_cap": Decimal("90"),
            "cashback_expiry_days": 30,
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    yield configured
    app.dependency_overrides[get_settings] = lambda: _test_settings()


async def _stall(db, name="Ordinary Stall", price="200.00"):
    from app.core.security import TokenAudience
    from app.db.models.menu import MenuItem
    from app.db.models.user import User, UserRole
    from app.db.models.vendor import Vendor

    from tests.conftest import _token

    owner = User(email=f"cb.{uuid.uuid4().hex[:10]}@gmail.com", role=UserRole.VENDOR)
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


async def _place(client, headers, stall, item, **kw):
    body = {
        "vendor_id": str(stall.id),
        "items": [{"menu_item_id": str(item.id), "quantity": kw.get("quantity", 1)}],
        "fulfilment_type": kw.get("fulfilment", "dine_in"),
    }
    if body["fulfilment_type"] == "delivery":
        body["delivery_location"] = "hostel_5"
    if kw.get("cod"):
        body["payment_method"] = "cod"
    if kw.get("redeem"):
        body["redeem_cashback"] = True
    return await client.post("/orders", headers=headers, json=body)


async def _finish(client, vendor_headers, order_id, *, delivery=False):
    """Walk an order to completed through the stall's own route."""
    steps = ["accepted", "preparing", "ready"]
    steps += ["out_for_delivery", "completed"] if delivery else ["completed"]
    for step in steps:
        r = await client.patch(
            f"/vendors/me/orders/{order_id}/status",
            headers=vendor_headers,
            json={"status": step},
        )
        assert r.status_code == 200, (step, r.text)
    return r


async def _balance(client, headers, kind="normal"):
    r = await client.get("/cashback", headers=headers)
    assert r.status_code == 200, r.text
    wallet = next(w for w in r.json()["wallets"] if w["kind"] == kind)
    return Decimal(str(wallet["balance"]))


class TestEarning:
    async def test_a_completed_prepaid_order_earns(
        self, client, customer, db, pay, cashback_on
    ):
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        order = (await _place(client, headers, stall, item)).json()
        await pay(order["id"])
        await _finish(client, vendor_headers, order["id"])

        # 20% of ₹200, under the ₹40 cap.
        assert await _balance(client, headers) == Decimal("40")

    async def test_nothing_is_earned_before_completion(
        self, client, customer, db, pay, cashback_on
    ):
        """A credit at placement belongs to an order the stall may still reject."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        order = (await _place(client, headers, stall, item)).json()
        await pay(order["id"])
        await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "accepted"},
        )

        assert await _balance(client, headers) == Decimal("0")

    async def test_gourmet_pays_its_own_rate(
        self, client, customer, db, pay, cashback_on
    ):
        _, headers = customer
        stall, item, vendor_headers = await _stall(db, name="Gourmet Kitchen")
        order = (await _place(client, headers, stall, item)).json()
        await pay(order["id"])
        await _finish(client, vendor_headers, order["id"])

        # 60% of ₹200 is ₹120, capped at ₹90.
        assert await _balance(client, headers, "gourmet") == Decimal("90")
        assert await _balance(client, headers, "normal") == Decimal("0")

    async def test_the_stall_name_is_matched_loosely(
        self, client, customer, db, pay, cashback_on
    ):
        """Case and surrounding space, because the name is typed twice by two
        people - once into a Railway variable and once into a signup form."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db, name="  gourmet kitchen ")
        order = (await _place(client, headers, stall, item)).json()
        await pay(order["id"])
        await _finish(client, vendor_headers, order["id"])

        assert await _balance(client, headers, "gourmet") == Decimal("90")

    async def test_an_unnamed_gourmet_setting_means_no_gourmet_tier(
        self, client, customer, db, pay
    ):
        """The suite's default, and production's until somebody names a stall.

        Worth a test of its own: the expensive rate must not be reachable by
        accident, so a stall actually called Gourmet Kitchen earns the ordinary
        rate while the setting is empty.
        """
        _, headers = customer
        stall, item, vendor_headers = await _stall(db, name="Gourmet Kitchen")
        order = (await _place(client, headers, stall, item)).json()
        await pay(order["id"])
        await _finish(client, vendor_headers, order["id"])

        assert await _balance(client, headers, "gourmet") == Decimal("0")
        assert await _balance(client, headers, "normal") == Decimal("40")

    async def test_completing_twice_credits_once(
        self, client, customer, db, pay, cashback_on
    ):
        """Two routes reach COMPLETED, and a tap can be repeated.

        The transition table refuses the second move, so this asserts the
        idempotence holds even where the status change does not - the credit must
        not depend on the transition guard being the thing that stops it.
        """
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        order = (await _place(client, headers, stall, item)).json()
        await pay(order["id"])
        await _finish(client, vendor_headers, order["id"])
        await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "completed"},
        )

        assert await _balance(client, headers) == Decimal("40")

    async def test_a_cash_delivery_earns_nothing(
        self, client, customer, db, cashback_on
    ):
        """The user's rule, and it has a reason: pay on delivery already exposes
        a stall to cooking food nobody pays for, and crediting on top would make
        a refused-at-the-door order cost twice."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        placed = await _place(
            client, headers, stall, item, fulfilment="delivery", cod=True
        )
        assert placed.status_code == 201, placed.text
        order = placed.json()
        # Out of the kitchen first: collection is only allowed once the owner is
        # actually with the customer, which assert_collectable enforces.
        for step in ("accepted", "preparing", "ready", "out_for_delivery"):
            r = await client.patch(
                f"/vendors/me/orders/{order['id']}/status",
                headers=vendor_headers,
                json={"status": step},
            )
            assert r.status_code == 200, (step, r.text)

        took = await client.post(
            f"/vendors/me/orders/{order['id']}/collect",
            headers=vendor_headers,
            json={"method": "cash"},
        )
        assert took.status_code == 200, took.text

        done = await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "completed", "delivery_code": order["delivery_code"]},
        )
        assert done.status_code == 200, done.text

        assert await _balance(client, headers) == Decimal("0")

    async def test_a_prepaid_delivery_does_earn(
        self, client, customer, db, pay, cashback_on
    ):
        """The exclusion is about cash, not about delivery."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        order = (
            await _place(client, headers, stall, item, fulfilment="delivery")
        ).json()
        await pay(order["id"])
        await client.post(
            f"/vendors/me/orders/{order['id']}/self-deliver", headers=vendor_headers
        )
        await _finish(client, vendor_headers, order["id"], delivery=True)

        assert await _balance(client, headers) == Decimal("40")

    async def test_an_order_that_redeemed_earns_nothing(
        self, client, customer, db, pay, cashback_on
    ):
        """Or a balance refills itself and the promotion never ends."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)

        first = (await _place(client, headers, stall, item)).json()
        await pay(first["id"])
        await _finish(client, vendor_headers, first["id"])
        assert await _balance(client, headers) == Decimal("40")

        second = (await _place(client, headers, stall, item, redeem=True)).json()
        assert Decimal(second["cashback_applied"]) == Decimal("40.00")
        await pay(second["id"])
        await _finish(client, vendor_headers, second["id"])

        # The ₹40 was spent and nothing replaced it.
        assert await _balance(client, headers) == Decimal("0")


class TestSpending:
    async def test_the_discount_comes_off_what_is_owed_not_off_the_stall(
        self, client, customer, db, pay, cashback_on
    ):
        """The central decision of this feature, asserted on the wire.

        Hungry Birds funds the promotion, so `total_amount` keeps saying what
        the stall is owed for the food and `amount_due` says what the customer
        hands over. Collapsing the two would quietly under-pay every stall that
        a student redeems at.
        """
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        first = (await _place(client, headers, stall, item)).json()
        await pay(first["id"])
        await _finish(client, vendor_headers, first["id"])

        second = (await _place(client, headers, stall, item, redeem=True)).json()

        assert Decimal(second["total_amount"]) == Decimal("200.00")
        assert Decimal(second["cashback_applied"]) == Decimal("40.00")
        assert Decimal(second["amount_due"]) == Decimal("160.00")

    async def test_redeeming_with_an_empty_wallet_is_not_an_error(
        self, client, customer, db, cashback_on
    ):
        """A student ticks a box; the answer is "nothing to apply".

        Failing their order over an empty balance would be absurd, and it is the
        obvious way to write this wrong.
        """
        _, headers = customer
        stall, item, _ = await _stall(db)

        placed = await _place(client, headers, stall, item, redeem=True)

        assert placed.status_code == 201, placed.text
        assert Decimal(placed.json()["cashback_applied"]) == Decimal("0.00")

    async def test_a_gourmet_balance_is_unusable_at_an_ordinary_stall(
        self, client, customer, db, pay, cashback_on
    ):
        _, headers = customer
        gourmet, g_item, g_headers = await _stall(db, name="Gourmet Kitchen")
        ordinary, o_item, _ = await _stall(db, name="Ordinary Stall")

        earner = (await _place(client, headers, gourmet, g_item)).json()
        await pay(earner["id"])
        await _finish(client, g_headers, earner["id"])
        assert await _balance(client, headers, "gourmet") == Decimal("90")

        spent = (await _place(client, headers, ordinary, o_item, redeem=True)).json()

        assert Decimal(spent["cashback_applied"]) == Decimal("0.00")
        assert await _balance(client, headers, "gourmet") == Decimal("90")

    async def test_an_ordinary_balance_is_unusable_at_gourmet(
        self, client, customer, db, pay, cashback_on
    ):
        _, headers = customer
        ordinary, o_item, o_headers = await _stall(db, name="Ordinary Stall")
        gourmet, g_item, _ = await _stall(db, name="Gourmet Kitchen")

        earner = (await _place(client, headers, ordinary, o_item)).json()
        await pay(earner["id"])
        await _finish(client, o_headers, earner["id"])

        spent = (await _place(client, headers, gourmet, g_item, redeem=True)).json()

        assert Decimal(spent["cashback_applied"]) == Decimal("0.00")
        assert await _balance(client, headers, "normal") == Decimal("40")

    async def test_the_share_of_the_cart_binds_on_a_small_order(
        self, client, customer, db, pay, cashback_on
    ):
        """₹40 in the wallet and a ₹100 cart: 20% of it is ₹20, so ₹20."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        big = (await _place(client, headers, stall, item)).json()
        await pay(big["id"])
        await _finish(client, vendor_headers, big["id"])

        small, small_item, _ = await _stall(db, name="Small Stall", price="100.00")
        spent = (await _place(client, headers, small, small_item, redeem=True)).json()

        assert Decimal(spent["cashback_applied"]) == Decimal("20.00")
        assert Decimal(spent["amount_due"]) == Decimal("80.00")

    async def test_a_cash_delivery_may_redeem(
        self, client, customer, db, pay, cashback_on
    ):
        """The asymmetry the user asked for: no earning on cash, but spending is
        fine. And the figure the rider collects has to be the reduced one."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        earner = (await _place(client, headers, stall, item)).json()
        await pay(earner["id"])
        await _finish(client, vendor_headers, earner["id"])

        cash = (
            await _place(
                client, headers, stall, item, fulfilment="delivery", cod=True, redeem=True
            )
        ).json()

        assert Decimal(cash["cashback_applied"]) == Decimal("40.00")
        assert Decimal(cash["amount_due"]) == Decimal("160.00")

    async def test_the_collect_guard_names_the_reduced_figure(
        self, client, customer, db, pay, cashback_on
    ):
        """What a stall is told to collect, and the reason amount_due exists.

        Before this the guard quoted the gross, so an owner redeeming student
        would be told to collect ₹200 on an order the customer owed ₹160 for.
        """
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        earner = (await _place(client, headers, stall, item)).json()
        await pay(earner["id"])
        await _finish(client, vendor_headers, earner["id"])

        cash = (
            await _place(
                client, headers, stall, item, fulfilment="delivery", cod=True, redeem=True
            )
        ).json()
        for step in ("accepted", "preparing", "ready", "out_for_delivery"):
            await client.patch(
                f"/vendors/me/orders/{cash['id']}/status",
                headers=vendor_headers,
                json={"status": step},
            )

        refused = await client.patch(
            f"/vendors/me/orders/{cash['id']}/status",
            headers=vendor_headers,
            json={"status": "completed", "delivery_code": cash["delivery_code"]},
        )

        assert refused.status_code == 400, refused.text
        assert "160" in refused.json()["detail"]


class TestARefusedOrderGivesItBack:
    async def test_a_rejected_order_returns_the_redemption(
        self, client, customer, db, pay, cashback_on
    ):
        """Without this a stall rejecting an order keeps the student's cashback.

        It paid for food they never got, and no refund path touches it - the
        gateway never saw that part of the money.
        """
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        earner = (await _place(client, headers, stall, item)).json()
        await pay(earner["id"])
        await _finish(client, vendor_headers, earner["id"])

        spent = (await _place(client, headers, stall, item, redeem=True)).json()
        await pay(spent["id"])
        assert await _balance(client, headers) == Decimal("0")

        r = await client.patch(
            f"/vendors/me/orders/{spent['id']}/status",
            headers=vendor_headers,
            json={"status": "rejected"},
        )
        assert r.status_code == 200, r.text

        assert await _balance(client, headers) == Decimal("40")

    async def test_a_cancelled_order_returns_it_too(
        self, client, customer, db, pay, cashback_on
    ):
        """REFUNDABLE_ENDINGS rather than a named status, for the reason the
        refund path already learnt: a stall sending `cancelled` on a paid order
        used to close it and keep the money."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        earner = (await _place(client, headers, stall, item)).json()
        await pay(earner["id"])
        await _finish(client, vendor_headers, earner["id"])

        spent = (await _place(client, headers, stall, item, redeem=True)).json()
        await pay(spent["id"])
        await client.patch(
            f"/vendors/me/orders/{spent['id']}/status",
            headers=vendor_headers,
            json={"status": "cancelled"},
        )

        assert await _balance(client, headers) == Decimal("40")

    async def test_returning_twice_credits_once(
        self, client, customer, db, pay, cashback_on
    ):
        """The refusal path is re-enterable, and a second return would mint money.

        The transition table refuses the second rejection, so this asserts the
        idempotence does not rely on that guard being what stops it.
        """
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        earner = (await _place(client, headers, stall, item)).json()
        await pay(earner["id"])
        await _finish(client, vendor_headers, earner["id"])

        spent = (await _place(client, headers, stall, item, redeem=True)).json()
        await pay(spent["id"])
        for _ in range(3):
            await client.patch(
                f"/vendors/me/orders/{spent['id']}/status",
                headers=vendor_headers,
                json={"status": "rejected"},
            )

        assert await _balance(client, headers) == Decimal("40")

    async def test_a_refused_order_that_redeemed_nothing_returns_nothing(
        self, client, customer, db, pay, cashback_on
    ):
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        order = (await _place(client, headers, stall, item)).json()
        await pay(order["id"])
        await client.patch(
            f"/vendors/me/orders/{order['id']}/status",
            headers=vendor_headers,
            json={"status": "rejected"},
        )

        assert await _balance(client, headers) == Decimal("0")


class TestTheQuote:
    async def test_it_agrees_with_what_the_order_actually_applies(
        self, client, customer, db, pay, cashback_on
    ):
        """The reason the endpoint exists rather than the client doing the maths.

        A student shown one number and charged against another stops trusting
        the app, and never reports it as a bug.
        """
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        earner = (await _place(client, headers, stall, item)).json()
        await pay(earner["id"])
        await _finish(client, vendor_headers, earner["id"])

        quoted = await client.get(
            "/cashback/quote",
            headers=headers,
            params={"vendor_id": str(stall.id), "subtotal": "200.00"},
        )
        assert quoted.status_code == 200, quoted.text

        placed = (await _place(client, headers, stall, item, redeem=True)).json()

        assert Decimal(str(quoted.json()["redeemable"])) == Decimal(
            placed["cashback_applied"]
        )
        assert Decimal(str(quoted.json()["payable"])) == Decimal(placed["amount_due"])

    async def test_it_says_which_wallet_and_which_percentage(
        self, client, customer, db, cashback_on
    ):
        _, headers = customer
        gourmet, _, _ = await _stall(db, name="Gourmet Kitchen")

        quoted = (
            await client.get(
                "/cashback/quote",
                headers=headers,
                params={"vendor_id": str(gourmet.id), "subtotal": "100.00"},
            )
        ).json()

        assert quoted["kind"] == "gourmet"
        assert quoted["percent"] == 60

    async def test_a_lying_subtotal_only_lies_to_its_own_screen(
        self, client, customer, db, pay, cashback_on
    ):
        """The quote's subtotal never reaches an order.

        A client claiming a ₹10,000 cart gets a quote for one; the order is
        still priced from the stall's own rows and redeems against that.
        """
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        earner = (await _place(client, headers, stall, item)).json()
        await pay(earner["id"])
        await _finish(client, vendor_headers, earner["id"])

        await client.get(
            "/cashback/quote",
            headers=headers,
            params={"vendor_id": str(stall.id), "subtotal": "10000.00"},
        )
        placed = (await _place(client, headers, stall, item, redeem=True)).json()

        assert Decimal(placed["total_amount"]) == Decimal("200.00")
        assert Decimal(placed["cashback_applied"]) == Decimal("40.00")

    async def test_an_unknown_stall_is_a_404(self, client, customer, cashback_on):
        _, headers = customer
        r = await client.get(
            "/cashback/quote",
            headers=headers,
            params={"vendor_id": str(uuid.uuid4()), "subtotal": "100.00"},
        )
        assert r.status_code == 404


class TestWhatTheStudentIsShown:
    async def test_both_wallets_are_returned_even_when_empty(
        self, client, customer, cashback_on
    ):
        """So the offers page can explain the difference rather than hiding the
        wallet somebody has not earned into yet."""
        _, headers = customer
        body = (await client.get("/cashback", headers=headers)).json()

        assert {w["kind"] for w in body["wallets"]} == {"normal", "gourmet"}
        assert all(Decimal(str(w["balance"])) == 0 for w in body["wallets"])

    async def test_the_entries_explain_the_balance(
        self, client, customer, db, pay, cashback_on
    ):
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        order = (await _place(client, headers, stall, item)).json()
        await pay(order["id"])
        await _finish(client, vendor_headers, order["id"])

        body = (await client.get("/cashback", headers=headers)).json()

        earned = [e for e in body["entries"] if e["reason"] == "earned"]
        assert len(earned) == 1
        assert Decimal(str(earned[0]["amount"])) == Decimal("40.00")
        # Named, so the page does not have to fetch every order to say where a
        # credit came from.
        assert earned[0]["stall_name"] == "Ordinary Stall"
        assert earned[0]["order_number"] == order["order_number"]
        assert earned[0]["expires_at"] is not None

    async def test_a_wallet_carries_its_rate_and_cap(self, client, customer, cashback_on):
        _, headers = customer
        body = (await client.get("/cashback", headers=headers)).json()

        gourmet = next(w for w in body["wallets"] if w["kind"] == "gourmet")
        assert gourmet["percent"] == 60
        assert Decimal(str(gourmet["cap"])) == Decimal("90")

    async def test_another_students_ledger_is_not_visible(
        self, client, customer, db, pay, cashback_on
    ):
        """Scoped to the caller, like every other customer route."""
        from app.core.security import TokenAudience
        from app.db.models.user import User, UserRole

        from tests.conftest import INSTITUTE, _token

        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        order = (await _place(client, headers, stall, item)).json()
        await pay(order["id"])
        await _finish(client, vendor_headers, order["id"])

        other = User(
            email=f"other.{uuid.uuid4().hex[:8]}@{INSTITUTE}",
            role=UserRole.CUSTOMER,
            full_name="Somebody Else",
            phone="+919876500099",
        )
        db.add(other)
        await db.commit()
        await db.refresh(other)

        body = (
            await client.get(
                "/cashback", headers=_token(other.id, TokenAudience.WEB)
            )
        ).json()

        assert body["entries"] == []
        assert all(Decimal(str(w["balance"])) == 0 for w in body["wallets"])

    async def test_signing_in_is_required(self, client, cashback_on):
        assert (await client.get("/cashback")).status_code == 401


class TestTheGatewayAgreesAboutWhatIsOwed:
    """The failure that would stop a paying customer, rather than let one through.

    Every money-bearing path reads `amount_due`. Miss one and the symptom is not
    a leak - it is Razorpay being asked for the gross while the customer is shown
    the net, and the amount check then rejecting their own correct payment. So
    these assert the QR is minted for the reduced figure and the webhook accepts
    exactly that.
    """

    async def test_the_qr_is_minted_for_the_reduced_figure(
        self, stub_razorpay, client, customer, db, pay, cashback_on
    ):
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        earner = (await _place(client, headers, stall, item)).json()
        await pay(earner["id"])
        await _finish(client, vendor_headers, earner["id"])

        cash = (
            await _place(
                client, headers, stall, item, fulfilment="delivery", cod=True, redeem=True
            )
        ).json()
        for step in ("accepted", "preparing", "ready", "out_for_delivery"):
            await client.patch(
                f"/vendors/me/orders/{cash['id']}/status",
                headers=vendor_headers,
                json={"status": step},
            )

        minted = await client.post(
            f"/vendors/me/orders/{cash['id']}/upi-qr", headers=vendor_headers
        )
        assert minted.status_code == 200, minted.text

        # ₹160 in paise, not ₹200.
        assert stub_razorpay["qrs"][-1]["payment_amount"] == 16000
        assert Decimal(str(minted.json()["amount"])) == Decimal("160.00")

    async def test_a_credit_for_the_reduced_figure_is_accepted(
        self, stub_razorpay, signed_webhook, client, customer, db, pay, cashback_on
    ):
        """Against amount_due. On the gross this answers amount_mismatch and the
        student is told they have not paid for an order they have."""
        from app.db.models.order import Order

        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        earner = (await _place(client, headers, stall, item)).json()
        await pay(earner["id"])
        await _finish(client, vendor_headers, earner["id"])

        cash = (
            await _place(
                client, headers, stall, item, fulfilment="delivery", cod=True, redeem=True
            )
        ).json()
        for step in ("accepted", "preparing", "ready", "out_for_delivery"):
            await client.patch(
                f"/vendors/me/orders/{cash['id']}/status",
                headers=vendor_headers,
                json={"status": step},
            )
        await client.post(
            f"/vendors/me/orders/{cash['id']}/upi-qr", headers=vendor_headers
        )
        qr_id = stub_razorpay["qrs"][-1]["id"]

        r = await signed_webhook(
            {
                "event": "qr_code.credited",
                "payload": {
                    "qr_code": {"entity": {"id": qr_id}},
                    "payment": {
                        "entity": {
                            "id": f"pay_{uuid.uuid4().hex[:14]}",
                            "status": "captured",
                            "amount": 16000,
                            "currency": "INR",
                        }
                    },
                },
            }
        )

        assert r.json()["status"] == "applied", r.text
        row = await db.get(Order, uuid.UUID(cash["id"]))
        await db.refresh(row)
        assert row.payment_status.value == "paid"

    async def test_a_credit_for_the_gross_is_still_refused(
        self, stub_razorpay, signed_webhook, client, customer, db, pay, cashback_on
    ):
        """The check is not merely relaxed. Paying ₹200 on an order that owes
        ₹160 is as wrong as paying ₹100, and means something has gone astray."""
        from app.db.models.order import Order

        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        earner = (await _place(client, headers, stall, item)).json()
        await pay(earner["id"])
        await _finish(client, vendor_headers, earner["id"])

        cash = (
            await _place(
                client, headers, stall, item, fulfilment="delivery", cod=True, redeem=True
            )
        ).json()
        for step in ("accepted", "preparing", "ready", "out_for_delivery"):
            await client.patch(
                f"/vendors/me/orders/{cash['id']}/status",
                headers=vendor_headers,
                json={"status": step},
            )
        await client.post(
            f"/vendors/me/orders/{cash['id']}/upi-qr", headers=vendor_headers
        )
        qr_id = stub_razorpay["qrs"][-1]["id"]

        r = await signed_webhook(
            {
                "event": "qr_code.credited",
                "payload": {
                    "qr_code": {"entity": {"id": qr_id}},
                    "payment": {
                        "entity": {"id": "pay_gross", "status": "captured", "amount": 20000}
                    },
                },
            }
        )

        assert r.json()["status"] == "amount_mismatch"
        row = await db.get(Order, uuid.UUID(cash["id"]))
        await db.refresh(row)
        assert row.payment_status.value == "due"

    async def test_an_online_order_opens_at_the_gateway_for_what_is_owed(
        self, stub_razorpay, client, customer, db, pay, cashback_on
    ):
        """The prepaid path, where the same mistake would charge the full price
        and pocket the discount."""
        _, headers = customer
        stall, item, vendor_headers = await _stall(db)
        earner = (await _place(client, headers, stall, item)).json()
        await pay(earner["id"])
        await _finish(client, vendor_headers, earner["id"])

        spent = (await _place(client, headers, stall, item, redeem=True)).json()
        session = await client.post(
            f"/orders/{spent['id']}/payment-session", headers=headers
        )
        assert session.status_code in (200, 201), session.text

        # Paise, which is how every Razorpay amount field is stated. 16000 is
        # ₹160 - what is owed - rather than the ₹200 the stall is credited.
        assert session.json()["amount"] == 16000
