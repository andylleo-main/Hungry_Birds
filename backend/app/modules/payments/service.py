"""Taking money for an order, and giving it back.

The governing rule is that this module records what the gateway tells us and
never adjudicates fulfilment. A webhook that can fail for a business reason is
exactly what must not exist: Razorpay retries anything it does not get a 2xx for,
for 24 hours, and a retry cannot fix a disagreement about whether a stall is open.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import BackgroundTasks
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.order import Order, OrderStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.session import async_session_factory
from app.core.tasks import fire_and_log
from app.modules.payments import mock, razorpay

logger = logging.getLogger(__name__)

# Added on top of the gateway's own payment window before an unpaid order is
# written off locally. The sum has to exceed that window, or we would cancel an
# order Razorpay is still willing to take money for - and then have to refund a
# payment for food nobody is making.
SWEEP_GRACE_MINUTES = 5


async def payment_for_gateway_order(
    gateway_order_id: str, db: AsyncSession
) -> Payment | None:
    """Find the payment row a gateway order id belongs to.

    **Razorpay mints its own order ids**, where Cashfree let us choose "hb_{uuid}"
    and parse the order back out of it. So this is a query rather than string
    surgery - which is why `payments.gateway_order_id` is uniquely indexed, and
    why there is no longer any id shape for a forged webhook to imitate.
    """
    result = await db.execute(
        select(Payment).where(Payment.gateway_order_id == gateway_order_id)
    )
    return result.scalar_one_or_none()


def event_id_for(body: dict, raw: bytes, header_event_id: str | None = None) -> str:
    """A stable identity for a webhook, for the idempotency ledger.

    Prefers Razorpay's own X-Razorpay-Event-Id, which is unique per event and
    repeated unchanged on every retry - exactly what the unique index over
    payment_events.event_id wants.

    This carries more weight than it did under Cashfree. Razorpay sends no
    timestamp with a webhook, so there is no staleness window to reject a replay
    with: the ledger is now the *only* thing standing between a captured request
    and it being applied twice. The digest fallback keeps that true even if the
    header is ever missing, because Razorpay replays the same body byte for byte.
    """
    if header_event_id:
        return f"evt:{header_event_id}"
    entity = ((body.get("payload") or {}).get("payment") or {}).get("entity") or {}
    refund = ((body.get("payload") or {}).get("refund") or {}).get("entity") or {}
    natural = entity.get("id") or refund.get("id")
    if natural:
        return f"{body.get('event', 'event')}:{natural}"
    return "sha256:" + hashlib.sha256(raw).hexdigest()


async def ensure_payment(order: Order, db: AsyncSession, settings: Settings) -> Payment:
    """The Payment row for an order, creating the gateway order the first time.

    One Razorpay order per order of ours, created once and reused. Razorpay allows
    several payment attempts against a single order, so a customer whose card is
    declined retries at the gateway rather than against a second order of ours -
    which is what makes being charged twice structurally impossible rather than
    unlikely.
    """
    result = await db.execute(select(Payment).where(Payment.order_id == order.id))
    payment = result.scalar_one_or_none()

    # A row left over from the other payment mode names an order the current
    # gateway has never heard of, so it has to be re-minted. Without this,
    # switching PAYMENTS_MODE would leave gateway_order_id pointing at a gateway
    # that cannot settle it, and the order could never be paid by anybody.
    if payment is not None and payment.gateway_order_id:
        if mock.is_mock(payment.gateway_order_id) == settings.payments_mock:
            return payment

    if settings.payments_mock:
        gateway_order_id = mock.gateway_order_id_for(order.id)
    else:
        response = await razorpay.create_order(
            # The number a student reads out on the phone. Putting it in the
            # receipt field makes a support call answerable from either side.
            receipt=order.order_number,
            # The authoritative figure, priced server-side when the order was
            # placed, less any promotional credit the student put towards it.
            # OrderCreate has no amount field and must never gain one - and the
            # flag that asks for a redemption is not one, because the server
            # works out how much from a balance it reads itself.
            amount=order.amount_due,
            notes={"order_id": str(order.id), "order_number": order.order_number},
            settings=settings,
        )
        gateway_order_id = str(response.get("id") or "")
        if not gateway_order_id:
            raise razorpay.RazorpayError("create_order returned no order id")

    if payment is None:
        payment = Payment(
            order_id=order.id,
            gateway_order_id=gateway_order_id,
            # What is being charged, which is what the webhook's amount check
            # compares against a few lines down. The stall's own figure is
            # orders.total_amount and is deliberately larger when cashback was
            # spent.
            amount=order.amount_due,
        )
        db.add(payment)
    else:
        payment.gateway_order_id = gateway_order_id
    await db.commit()
    await db.refresh(payment)
    return payment


def _paise_match(claimed, expected: Decimal) -> bool:
    """Compare money as whole paise, which is how Razorpay states every amount.

    Integers all the way, so there is nothing here for binary floating point to
    round: the only conversion is our own Decimal column into paise, and that is
    the one place it happens.
    """
    try:
        return int(claimed) == razorpay.to_paise(expected)
    except (TypeError, ValueError, ArithmeticError):
        return False


async def apply_payment_success(
    order: Order, payment: Payment, entity: dict, db: AsyncSession
) -> str:
    """Mark an order paid, if the payload says what it should.

    Returns the outcome recorded against the event. Never raises for a business
    disagreement - the caller answers 200 either way, because a retry cannot fix
    a wrong amount and Razorpay will keep sending for 24 hours until it gets one.

    `entity` is Razorpay's payment entity, from payload.payment.entity on a
    webhook or straight from the API on the checkout callback. Both carry the
    same fields, which is what lets the two paths share this.
    """
    from app.modules.orders.service import allocate_token, can_transition_payment

    if not _paise_match(entity.get("amount"), payment.amount):
        # Loud, and deliberately not auto-resolved. Either somebody is probing or
        # something is badly wrong, and both want a human.
        logger.error(
            "razorpay reported %s paise for order %s, which we priced at %s - not marking paid",
            entity.get("amount"),
            order.id,
            payment.amount,
        )
        payment.last_error = (
            f"amount mismatch: reported {entity.get('amount')} paise, "
            f"expected {razorpay.to_paise(payment.amount)}"
        )
        await db.commit()
        return "amount_mismatch"

    if (entity.get("currency") or "INR") != "INR":
        payment.last_error = f"unexpected currency {entity.get('currency')}"
        await db.commit()
        return "amount_mismatch"

    if not can_transition_payment(order.payment_status, PaymentStatus.PAID):
        # Already paid, or already refunded. Recorded, not applied.
        return "rejected_transition"

    order.payment_status = PaymentStatus.PAID
    payment.gateway_payment_id = str(entity.get("id") or "") or None
    payment.paid_at = datetime.now(timezone.utc)

    if order.status == OrderStatus.AWAITING_PAYMENT:
        # The moment the stall first sees it, and so the moment it earns a token
        # number. Allocating any earlier would spend numbers on checkouts nobody
        # completed, and the stall would call out 12 having never called 9.
        # allocate_token is idempotent, which is what makes a replayed webhook
        # safe here.
        order.status = OrderStatus.PLACED
        await allocate_token(order, db)

    await db.commit()
    return "applied"


async def apply_cod_upi_collected(order: Order, entity: dict, db: AsyncSession) -> str:
    """A customer scanned the rider's QR and the money landed.

    The point of routing a doorstep UPI payment through a gateway at all: the
    rider never has to be believed about whether it arrived, because Razorpay
    says so directly.

    Checked against the order rather than a payments row, because a
    pay-on-delivery order has no payments row - nothing was ever opened at the
    gateway for it. The fixed-amount QR means a short payment cannot be made in
    the first place, so this check is about a forged or misrouted webhook rather
    than about underpayment.

    Against `amount_due`, not `total_amount`. The QR is minted for what the
    customer owes, so comparing against the stall's gross would reject the
    customer's own correct payment on any order that spent cashback - the
    failure mode here is not "a mismatch slips through" but "a student pays and
    is told they did not".
    """
    from app.modules.orders.service import can_transition_payment

    if not _paise_match(entity.get("amount"), order.amount_due):
        logger.error(
            "qr credit of %s paise for order %s, which owes %s - not marking paid",
            entity.get("amount"),
            order.id,
            order.amount_due,
        )
        return "amount_mismatch"

    if not can_transition_payment(order.payment_status, PaymentStatus.PAID):
        return "rejected_transition"

    order.payment_status = PaymentStatus.PAID
    order.collected_via = "upi"
    await db.commit()
    return "applied"


async def apply_payment_failure(order: Order, entity: dict, db: AsyncSession) -> str:
    from app.modules.orders.service import can_transition_payment

    if not can_transition_payment(order.payment_status, PaymentStatus.FAILED):
        return "rejected_transition"
    order.payment_status = PaymentStatus.FAILED
    await db.commit()
    return "applied"


async def apply_refund_update(
    order: Order, payment: Payment, entity: dict, db: AsyncSession
) -> str:
    from app.modules.orders.service import can_transition_payment

    status = str(entity.get("status") or "").lower()

    target = {
        "processed": PaymentStatus.REFUNDED,
        "failed": PaymentStatus.REFUND_FAILED,
    }.get(status)
    if target is None:
        # "pending", or something Razorpay added later: nothing has changed yet,
        # and guessing is how a customer's money gets written off as returned
        # before it has been.
        return "rejected_transition"

    if entity.get("id"):
        payment.refund_id = str(entity["id"])[:64]

    if not can_transition_payment(order.payment_status, target):
        return "rejected_transition"

    order.payment_status = target
    if target is PaymentStatus.REFUND_FAILED:
        payment.last_error = f"refund {status}"
    await db.commit()
    return "applied"


async def start_refund(order_id: uuid.UUID, reason: str, db: AsyncSession) -> None:
    """Move an order's money state to refund-pending, without calling anybody.

    Split from the call on purpose: a stall rejecting an order must succeed while
    Razorpay is unreachable, so the state change commits inside the request and
    the network attempt happens afterwards.
    """
    from app.modules.orders.service import can_transition_payment

    order = await db.get(Order, order_id)
    if order is None or not can_transition_payment(order.payment_status, PaymentStatus.REFUND_PENDING):
        return

    result = await db.execute(select(Payment).where(Payment.order_id == order_id))
    payment = result.scalar_one_or_none()

    if payment is None:
        # Nothing was ever taken through the gateway, so there is nothing for it
        # to give back. Moving to REFUND_PENDING here would be worse than doing
        # nothing: attempt_refund returns silently on a missing payment row, so
        # the order would sit in refund-pending for ever, and any screen that
        # lists refunds in flight would show one that nobody will ever make.
        #
        # Reachable now that cash exists: a pay-on-delivery order is marked PAID
        # by a rider with no gateway payment behind it, and a stall cancelling one
        # afterwards owes the customer their notes back, not a refund API call. A
        # log line is a far better outcome than a stuck order.
        logger.warning(
            "refund wanted for order %s (%s) but it has no payment row - nothing to refund",
            order_id,
            reason,
        )
        return

    order.payment_status = PaymentStatus.REFUND_PENDING
    await db.commit()


async def attempt_refund(order_id: uuid.UUID, reason: str, settings: Settings) -> None:
    """Actually ask Razorpay for the money back.

    Runs after the response, in its own session - the request's session is closed
    by its dependency by the time a background task runs, and reusing it fails
    only under load, which is the worst time to find out.

    **This is the function that can pay a customer twice.** Cashfree accepted a
    refund id we chose, so repeating a request was free; Razorpay mints its own,
    so a naive retry creates a second refund and sends the money again. Two
    guards replace that lost guarantee:

    1. The payment row is claimed with SELECT ... FOR UPDATE SKIP LOCKED, and the
       lock is held across the gateway call rather than released before it. A
       second drain that arrives meanwhile is skipped by the database and returns
       without calling anybody.

       Holding a row lock across an HTTP request is normally worth avoiding, and
       it is deliberate here: the call is bounded by _REFUND_TIMEOUT, refunds are
       rare, and the alternative is a window in which two workers both believe
       they are the only one. A compare-and-set on the attempt counter was tried
       first and is **not** sufficient - a drain that reads after the first one
       commits sees the new value, swaps it legitimately, and goes on to refund
       again.

    2. Existing refunds are listed before one is created, and an existing one is
       adopted. That covers what no lock can: an attempt that reached Razorpay
       and then died before recording what came back, releasing the lock with the
       connection.
    """
    if not settings.payments_enabled:
        return

    if settings.payments_mock:
        # No money moved, so there is nothing to ask for back. Still recorded as
        # refunded rather than left pending, because the refund states exist to
        # tell somebody money is owed - and a mock order that sits in
        # refund_pending forever is a false alarm in every admin view.
        await _mark_mock_refunded(order_id, reason)
        return

    async with async_session_factory() as db:
        result = await db.execute(
            select(Payment).where(Payment.order_id == order_id).with_for_update(skip_locked=True)
        )
        payment = result.scalar_one_or_none()
        if payment is None:
            # Either there is no payment row, or another worker is holding this
            # one right now. Both mean there is nothing for us to do.
            logger.info("refund for order %s is not ours to make right now", order_id)
            return

        order = await db.get(Order, order_id)
        if order is None or order.payment_status is not PaymentStatus.REFUND_PENDING:
            return

        payment.refund_attempts += 1

        try:
            payment_id = payment.gateway_payment_id
            if not payment_id:
                # No webhook ever landed, so we hold no payment id. Razorpay knows
                # which payments were made against the order even when we do not.
                for attempt in await razorpay.order_payments(payment.gateway_order_id, settings):
                    if str(attempt.get("status")) == "captured":
                        payment_id = str(attempt.get("id"))
                        payment.gateway_payment_id = payment_id
                        break
            if not payment_id:
                raise razorpay.RazorpayError(
                    f"order {payment.gateway_order_id} has no captured payment to refund"
                )

            # Guard 2.
            existing = await razorpay.list_refunds(payment_id, settings)
            if existing:
                payment.refund_id = str(existing[0].get("id") or "")[:64] or None
                await db.commit()
                logger.info(
                    "adopted refund %s already open for order %s rather than making a second",
                    payment.refund_id,
                    order_id,
                )
                return

            created = await razorpay.refund(
                payment_id=payment_id,
                amount=payment.amount,
                notes={"order_id": str(order_id), "reason": reason[:100]},
                settings=settings,
            )
            payment.refund_id = str(created.get("id") or "")[:64] or None
            # Commits here, which is also what releases the lock taken above.
            await db.commit()
        except Exception as exc:
            # Left in refund_pending rather than marked failed: the money is
            # still owed and the next drain should try again. The error is
            # recorded so an admin can see why it is stuck - and committing it
            # is what releases the row for that next attempt.
            payment.last_error = str(exc)[:500]
            await db.commit()
            raise

        logger.info("refund requested for order %s (%s)", order_id, reason)


async def _mark_mock_refunded(order_id: uuid.UUID, reason: str) -> None:
    """Close out a mock refund locally, with the same transition rules."""
    from app.modules.orders.service import can_transition_payment

    async with async_session_factory() as db:
        order = await db.get(Order, order_id)
        if order is None:
            return
        if not can_transition_payment(order.payment_status, PaymentStatus.REFUNDED):
            return
        order.payment_status = PaymentStatus.REFUNDED
        await db.commit()
    logger.info("mock refund for order %s (%s) - no money moved", order_id, reason)


MAX_REFUND_ATTEMPTS = 8
# How many stuck refunds one read is allowed to re-drive. Small, because each
# one becomes a background call to Cashfree and a customer refreshing their
# orders page must not pay for a backlog with latency.
REFUND_DRAIN_BATCH = 3


def _refund_backoff(attempts: int) -> timedelta:
    """How long to leave a failed refund alone before trying it again.

    Doubling, capped at an hour: roughly 1m, 2m, 4m ... which spans about four
    hours across MAX_REFUND_ATTEMPTS. Long enough that a Cashfree incident is
    over before the attempts run out, short enough that a customer is not
    waiting on a human.
    """
    return timedelta(minutes=min(2**attempts, 60))


async def drain_stuck_refunds(
    db: AsyncSession,
    settings: Settings,
    background: BackgroundTasks,
    vendor_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
) -> int:
    """Re-drive refunds that were started and never finished.

    attempt_refund runs once, as a background task, and re-raises on failure -
    leaving the order in refund_pending with the error recorded. Its own comment
    says "the next drain should try again", and until now there was no drain:
    refund_attempts was incremented and never read, so a gateway blip during a
    rejection lost a customer's money until somebody noticed by hand.

    Rides on the order lists for the same reason sweep_abandoned does - there is
    no scheduler in this project - and scoped the same way, so a busy read never
    turns into unbounded work. The scoping also happens to aim it well: the
    customer whose refund is stuck is the one refreshing their orders page.

    No distributed lock, and two concurrent reads can still pick the same row.
    What makes that survivable now lives in attempt_refund rather than here:
    it claims the attempt counter with a compare-and-set and lists existing
    refunds before creating one. Under Cashfree this was free, because the refund
    id was ours and reused; with Razorpay minting its own, those two guards are
    the only thing between a retry and a customer refunded twice.
    """
    if not settings.payments_enabled:
        return 0

    stmt = (
        select(Order.id, Payment.refund_attempts)
        .join(Payment, Payment.order_id == Order.id)
        .where(
            Order.payment_status.in_(
                [PaymentStatus.REFUND_PENDING, PaymentStatus.REFUND_FAILED]
            ),
            Payment.refund_attempts < MAX_REFUND_ATTEMPTS,
        )
        .order_by(Payment.updated_at)
        .limit(REFUND_DRAIN_BATCH)
    )
    if vendor_id is not None:
        stmt = stmt.where(Order.vendor_id == vendor_id)
    if customer_id is not None:
        stmt = stmt.where(Order.customer_id == customer_id)

    now = datetime.now(timezone.utc)
    rows = (await db.execute(stmt)).all()

    started = 0
    for order_id, attempts in rows:
        payment = (
            await db.execute(select(Payment).where(Payment.order_id == order_id))
        ).scalar_one_or_none()
        if payment is None:
            continue
        last = payment.updated_at
        if last is not None and now - last < _refund_backoff(attempts):
            continue
        background.add_task(
            fire_and_log,
            "drain_stuck_refund",
            lambda oid=order_id: attempt_refund(oid, "retrying an unfinished refund", settings),
        )
        started += 1

    if started:
        logger.info("re-driving %s unfinished refund(s)", started)
    return started


async def sweep_abandoned(
    db: AsyncSession,
    settings: Settings,
    vendor_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
) -> int:
    """Write off orders nobody ever paid for.

    There is no scheduler in this project, so this runs opportunistically from
    the reads that would otherwise show these rows. Nothing is deleted - an
    abandoned order is still a record - and the window is deliberately longer
    than the gateway's own so a payment it would still accept is never cancelled
    underneath it.

    The status predicate is load-bearing, twice over. An order the customer
    cancelled themselves must not be rewritten by a sweep; and a pay-on-delivery
    order is never AWAITING_PAYMENT/PENDING, which is exactly why cash orders are
    placed straight into the stall's queue rather than parked in the state this
    cancels twenty minutes later.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=settings.payment_window_minutes + SWEEP_GRACE_MINUTES
    )
    stmt = (
        update(Order)
        .where(
            Order.status == OrderStatus.AWAITING_PAYMENT,
            Order.payment_status == PaymentStatus.PENDING,
            Order.created_at < cutoff,
        )
        .values(status=OrderStatus.CANCELLED, payment_status=PaymentStatus.EXPIRED)
    )
    # Always scoped to one person's rows, so a busy read never turns into an
    # unbounded write across the whole table.
    if vendor_id is not None:
        stmt = stmt.where(Order.vendor_id == vendor_id)
    if customer_id is not None:
        stmt = stmt.where(Order.customer_id == customer_id)

    result = await db.execute(stmt)
    if result.rowcount:
        await db.commit()
    return result.rowcount or 0
