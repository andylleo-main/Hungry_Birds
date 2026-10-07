"""Working out what cashback is owed, what can be spent, and what is left.

The arithmetic lives here and nowhere else, because two callers have to agree
exactly: the quote a customer is shown at checkout and the redemption actually
applied when they place the order. If those two ever disagree, a student sees one
number and is charged against another, which is the kind of bug nobody reports
as a bug - they just stop trusting the app.

The balance is the interesting part. It is a walk over the ledger rather than a
sum, and `live_balances` says why.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.cashback import CashbackEntry, CashbackKind, CashbackReason
from app.db.models.order import FulfilmentType, Order
from app.db.models.user import User
from app.db.models.vendor import Vendor

log = logging.getLogger(__name__)

RUPEE = Decimal("0.01")


def _floor_rupees(amount: Decimal) -> Decimal:
    """Down to whole rupees.

    Always down, never nearest: rounding a cap upwards hands out money the
    setting said not to, and a student is never worse off by a visible amount -
    the most anybody loses is 99 paise off a discount they are being given.

    Whole rupees because every figure in this app is read aloud, printed on a
    58mm ticket, or typed into a UPI app. Nobody collects 34 paise.
    """
    return amount.quantize(Decimal("1"), rounding=ROUND_DOWN)


def kind_for(vendor: Vendor, settings: Settings) -> CashbackKind:
    """Which wallet this stall belongs to.

    Matched on the stall's name, which is how the user identifies the special
    kitchen - not a flag on the row, so renaming it is a Railway variable rather
    than a migration. Compared case-insensitively and stripped, because the name
    is typed in two places by two people.

    An unset setting means no stall is Gourmet, so the expensive tier is off
    until somebody deliberately names it.
    """
    wanted = settings.gourmet_kitchen_name.strip().casefold()
    if wanted and vendor.stall_name.strip().casefold() == wanted:
        return CashbackKind.GOURMET
    return CashbackKind.NORMAL


@dataclass(frozen=True)
class Rate:
    """What a kind of kitchen pays back, and the most it will pay on one order."""

    percent: int
    cap: Decimal


def rate_for(kind: CashbackKind, settings: Settings, *, on: datetime | None = None) -> Rate:
    """The earning rate for this kind of stall.

    `on` is threaded through for the probability distribution that is meant to
    replace the flat rate once CASHBACK_END_DATE passes. **It currently changes
    nothing**: the user asked to keep flat 20/60 until they specify the
    distribution, so this returns the same Rate either side of the date. The
    parameter and the setting exist so that plugging the distribution in later is
    an edit to this one function rather than a redesign of its callers.

    Worth stating plainly, because it is the risk the user accepted: a
    CASHBACK_END_DATE that passes unnoticed means full promotional rates keep
    being paid.
    """
    del on  # See above. Deliberately unused until the distribution is specified.
    if kind is CashbackKind.GOURMET:
        return Rate(settings.cashback_gourmet_percent, Decimal(settings.cashback_gourmet_cap))
    return Rate(settings.cashback_normal_percent, Decimal(settings.cashback_normal_cap))


def earned_on(subtotal: Decimal, rate: Rate) -> Decimal:
    """What an order of this value earns: a percentage, capped.

    Computed on the gross - the value of the food bought - rather than on what
    the customer paid after a discount. Not that it matters today, since an order
    that redeemed earns nothing at all.
    """
    if subtotal <= 0 or rate.percent <= 0:
        return Decimal("0")
    percentage = Decimal(subtotal) * Decimal(rate.percent) / Decimal(100)
    return _floor_rupees(min(percentage, rate.cap))


def spendable_on(subtotal: Decimal, balance: Decimal, rate: Rate) -> Decimal:
    """The most of a balance that may be put towards a cart of this size.

    Three ceilings, and the smallest wins: the same percentage the kind earns at,
    what the student actually holds, and the cart itself. The percentage ceiling
    is the one the user specified - "max 20% of cart value for normal kitchen and
    60% for gk" - and it is also what guarantees `amount_due` never reaches zero,
    so there is no free order and no zero-rupee gateway call to handle.
    """
    if subtotal <= 0 or balance <= 0 or rate.percent <= 0:
        return Decimal("0")
    share = Decimal(subtotal) * Decimal(rate.percent) / Decimal(100)
    return _floor_rupees(min(share, Decimal(balance), Decimal(subtotal)))


@dataclass
class _Lot:
    """One credit, and how much of it is left."""

    expires_at: datetime | None
    remaining: Decimal

    def alive_at(self, moment: datetime) -> bool:
        return self.expires_at is None or self.expires_at > moment


def live_balances(
    entries: list[CashbackEntry], now: datetime
) -> dict[CashbackKind, Decimal]:
    """Replay a ledger and return what is still spendable, per kind.

    **Not a sum**, and the reason is worth keeping: with per-credit expiry a sum
    is simply wrong. Take a ₹40 credit that expires on 1 November, spent in full
    on 15 October. Sum the unexpired credits on 2 November and you get ₹0; add
    the ₹40 debit and the balance reads *minus* ₹40. The debit consumed a credit
    that has since expired, and only a walk knows that.

    So this replays chronologically, holding open lots, and spends the
    soonest-expiring lot first - which is the order that leaves a student with
    the most usable balance afterwards, and is what anybody would do by hand.

    A redemption that cannot be covered by the lots alive when it happened means
    the ledger disagrees with itself: a bug, a partial write, or a hand repair.
    It is logged and clamped rather than raised, because this function is on
    every read path including the offers page, and a page that will not render is
    a worse answer to "something is inconsistent" than a page showing zero.
    """
    lots: dict[CashbackKind, list[_Lot]] = {kind: [] for kind in CashbackKind}

    for entry in sorted(entries, key=lambda e: e.created_at):
        amount = Decimal(entry.amount)
        if amount >= 0:
            # EARNED, and RETURNED - a refused order giving a redemption back.
            # Both behave as credits with their own expiry; see return_redemption
            # for why a return gets a fresh clock rather than the old one.
            lots[entry.kind].append(_Lot(entry.expires_at, amount))
            continue

        owed = -amount
        alive = [lot for lot in lots[entry.kind] if lot.alive_at(entry.created_at)]
        # Soonest expiry first. None last, since a credit that never expires is
        # the one to keep for later.
        alive.sort(key=lambda lot: (lot.expires_at is None, lot.expires_at))
        for lot in alive:
            if owed <= 0:
                break
            take = min(lot.remaining, owed)
            lot.remaining -= take
            owed -= take
        if owed > 0:
            log.warning(
                "cashback ledger inconsistent: entry %s spends %s more than its "
                "lots held; clamping",
                entry.id,
                owed,
            )

    return {
        kind: sum((lot.remaining for lot in kind_lots if lot.alive_at(now)), Decimal("0"))
        for kind, kind_lots in lots.items()
    }


def next_expiry(entries: list[CashbackEntry], kind: CashbackKind, now: datetime) -> datetime | None:
    """When the soonest unexpired credit of this kind runs out.

    For the offers page, which has to be able to say "₹40 expiring 6 November"
    rather than leaving a student to discover it. Approximate on purpose: it is
    the earliest expiry still in play, not the expiry of the part of the balance
    that survives, which nobody could act on differently.
    """
    dates = [
        entry.expires_at
        for entry in entries
        if entry.kind is kind
        and Decimal(entry.amount) > 0
        and entry.expires_at is not None
        and entry.expires_at > now
    ]
    return min(dates) if dates else None


async def entries_for(user_id: uuid.UUID, db: AsyncSession) -> list[CashbackEntry]:
    result = await db.execute(
        select(CashbackEntry)
        .where(CashbackEntry.user_id == user_id)
        .order_by(CashbackEntry.created_at)
    )
    return list(result.scalars().all())


async def balance_for(
    user_id: uuid.UUID, kind: CashbackKind, db: AsyncSession
) -> Decimal:
    entries = await entries_for(user_id, db)
    return live_balances(entries, datetime.now(timezone.utc))[kind]


async def lock_wallet(user_id: uuid.UUID, db: AsyncSession) -> None:
    """Serialise one student's redemptions.

    Reading a balance and then spending against it is two statements, so two
    checkouts in the same instant both read the same balance and both spend it -
    the same hazard VendorTokenCounter documents at length for token numbers.

    A row lock on the user, held to commit, rather than anything exotic. The user
    row is already the natural thing to lock: it is the wallet's owner, there is
    exactly one, and nothing else in the request wants it.
    """
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())


def earns_cashback(order: Order) -> bool:
    """Whether this order earns anything at all, per the user's three exclusions.

    Each one has a reason worth keeping:

      * **Pay on delivery, on a delivery.** The exposure pay-on-delivery already
        carries is a stall cooking food that is never paid for; crediting money
        back on top of it would make a cancelled-at-the-door order cost twice.
      * **Cashback was redeemed.** Otherwise a balance refills itself and the
        promotion never ends.
      * **A coupon was applied.** One promotion per order. The column lands with
        coupons in a later phase; the check is written now so that phase has
        nothing to remember.
    """
    if order.payment_method == "cod" and order.fulfilment_type is FulfilmentType.DELIVERY:
        return False
    if Decimal(order.cashback_applied) > 0:
        return False
    # Coupons do not exist yet. getattr rather than a bare attribute so this
    # keeps working either side of the phase that adds the column.
    if Decimal(getattr(order, "coupon_discount", 0) or 0) > 0:
        return False
    return True


def _expiry_from(now: datetime, settings: Settings) -> datetime | None:
    """When a credit minted now runs out.

    Frozen onto the row by the caller, never recomputed. Changing
    CASHBACK_EXPIRY_DAYS afterwards must not retroactively kill or revive a
    balance a student has already been shown a date for.

    Zero or less means no expiry, which is a usable way to turn expiry off
    without a code change.
    """
    if settings.cashback_expiry_days <= 0:
        return None
    return now + timedelta(days=settings.cashback_expiry_days)


async def _already(order_id: uuid.UUID, reason: CashbackReason, db: AsyncSession) -> bool:
    result = await db.execute(
        select(CashbackEntry.id).where(
            CashbackEntry.order_id == order_id, CashbackEntry.reason == reason
        )
    )
    return result.first() is not None


async def redeem_onto(
    order: Order,
    vendor: Vendor,
    subtotal: Decimal,
    db: AsyncSession,
    settings: Settings,
) -> Decimal:
    """Spend as much of this student's matching balance as the rules allow.

    Called from place_order, inside its transaction, after the basket has been
    priced from the stall's own rows. Sets `order.cashback_applied` and writes
    the debit; the caller commits both together, so an order can never exist
    with a discount that was not paid for out of a balance.

    The wallet is locked first - see `lock_wallet`.

    Returns what was applied, which is zero when there is nothing to spend. A
    student asking to redeem with an empty balance is not an error: they ticked a
    box, the answer is "nothing to apply", and failing their order over it would
    be absurd.
    """
    await lock_wallet(order.customer_id, db)

    kind = kind_for(vendor, settings)
    rate = rate_for(kind, settings)
    entries = await entries_for(order.customer_id, db)
    balance = live_balances(entries, datetime.now(timezone.utc))[kind]

    amount = spendable_on(subtotal, balance, rate)
    if amount <= 0:
        return Decimal("0")

    order.cashback_applied = amount
    db.add(
        CashbackEntry(
            user_id=order.customer_id,
            kind=kind,
            # Negative, because the ledger reads in one direction.
            amount=-amount,
            reason=CashbackReason.REDEEMED,
            order_id=order.id,
            # Nothing to expire: this is money leaving.
            expires_at=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    return amount


async def credit_for_completed_order(
    order: Order, db: AsyncSession, settings: Settings
) -> Decimal:
    """Earn cashback on an order that has just been completed.

    **Completion, not placement.** A credit at placement is money minted by an
    order the stall may still reject, and taking it back afterwards is a second
    reversal path nobody would remember to write.

    Called from both routes that can reach COMPLETED - the stall's and the
    rider's - so it has to be idempotent. It is, twice over: a read first for the
    good path, and a unique index underneath for the race. The nested
    transaction is what keeps an IntegrityError from poisoning the caller's
    transaction, which on this route would turn a duplicate tap into a 500 on an
    order that is already finished.
    """
    if not earns_cashback(order):
        return Decimal("0")
    if await _already(order.id, CashbackReason.EARNED, db):
        return Decimal("0")

    vendor = await db.get(Vendor, order.vendor_id)
    if vendor is None:
        return Decimal("0")

    now = datetime.now(timezone.utc)
    kind = kind_for(vendor, settings)
    amount = earned_on(Decimal(order.total_amount), rate_for(kind, settings, on=now))
    if amount <= 0:
        return Decimal("0")

    try:
        async with db.begin_nested():
            db.add(
                CashbackEntry(
                    user_id=order.customer_id,
                    kind=kind,
                    amount=amount,
                    reason=CashbackReason.EARNED,
                    order_id=order.id,
                    expires_at=_expiry_from(now, settings),
                    created_at=now,
                )
            )
    except IntegrityError:
        # The index fired, so somebody else credited this order between the read
        # above and here. Nothing to do and nothing wrong.
        return Decimal("0")

    return amount


async def return_redemption(order: Order, db: AsyncSession, settings: Settings) -> Decimal:
    """Give back what a student spent on an order the stall then refused.

    Not in the original brief, and not optional. Without it a stall rejecting an
    order keeps the customer's cashback: their money pays for food they never
    got, and no refund path touches it because the gateway never saw it.

    The kind is read back off the original debit rather than re-derived from the
    stall, so a stall renamed into or out of Gourmet Kitchen between the order
    and its refusal cannot move a student's money between wallets.

    **The returned credit gets a fresh expiry**, not the remains of the old one.
    Reconstructing which lots the redemption consumed would need the ledger to
    record it, and the student did nothing wrong - their order was refused. A
    slightly longer liability is the right side to err on, and it is bounded by
    the same setting as everything else.
    """
    applied = Decimal(order.cashback_applied)
    if applied <= 0:
        return Decimal("0")
    if await _already(order.id, CashbackReason.RETURNED, db):
        return Decimal("0")

    spent = (
        await db.execute(
            select(CashbackEntry).where(
                CashbackEntry.order_id == order.id,
                CashbackEntry.reason == CashbackReason.REDEEMED,
            )
        )
    ).scalars().first()
    if spent is None:
        # A discount with no debit behind it. That should be impossible - they
        # are written in one transaction - so say so rather than inventing a
        # wallet to pay it back into.
        log.error("order %s has cashback_applied but no redemption entry", order.id)
        return Decimal("0")

    now = datetime.now(timezone.utc)

    try:
        async with db.begin_nested():
            db.add(
                CashbackEntry(
                    user_id=order.customer_id,
                    kind=spent.kind,
                    amount=applied,
                    reason=CashbackReason.RETURNED,
                    order_id=order.id,
                    expires_at=_expiry_from(now, settings),
                    created_at=now,
                )
            )
    except IntegrityError:
        return Decimal("0")

    return applied
