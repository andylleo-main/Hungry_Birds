"""Taking money for an order, and giving it back.

The governing rule is that this module records what the gateway tells us and
never adjudicates fulfilment. A webhook that can fail for a business reason is
exactly what must not exist: Cashfree retries anything it does not get a 2xx for,
and a retry cannot fix a disagreement about whether a stall is open.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.order import Order, OrderStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.session import async_session_factory
from app.modules.payments import cashfree, mock

logger = logging.getLogger(__name__)

# Added on top of Cashfree's own order expiry before an unpaid order is written
# off locally. The sum has to exceed the gateway's window, or we would cancel an
# order Cashfree is still willing to take money for - and then have to refund a
# payment for food nobody is making.
SWEEP_GRACE_MINUTES = 5


def cf_order_id_for(order_id: uuid.UUID) -> str:
    """Our id for the Cashfree order. Derived, so it never needs looking up."""
    return f"hb_{order_id}"


def order_id_from_cf(cf_order_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(cf_order_id.removeprefix("hb_"))
    except ValueError:
        return None


def refund_id_for(order_id: uuid.UUID) -> str:
    """One refund id per order, reused on every attempt.

    Cashfree is idempotent on this, so a retry can never pay a customer twice.
    Generating a fresh one per attempt is the bug that would.
    """
    return f"rf_{order_id}"


def event_id_for(body: dict, timestamp: str, raw: bytes) -> str:
    """A stable identity for a webhook, for the idempotency ledger.

    Prefers whatever id Cashfree put in the payload. Falls back to a digest of
    the signed timestamp and body, which is stable across retries because
    Cashfree replays both unchanged.
    """
    data = body.get("data") or {}
    payment = data.get("payment") or {}
    refund = data.get("refund") or {}
    natural = payment.get("cf_payment_id") or refund.get("refund_id")
    if natural:
        return f"{body.get('type', 'event')}:{natural}"
    return "sha256:" + hashlib.sha256(timestamp.encode() + raw).hexdigest()


async def ensure_payment(order: Order, db: AsyncSession, settings: Settings) -> Payment:
    """The Payment row for an order, creating the Cashfree order the first time.

    One Cashfree order per order, created once and reused. Cashfree allows
    several attempts against a single order, so a customer whose card is declined
    retries at the gateway rather than against a second order of ours - which is
    what makes being charged twice structurally impossible rather than unlikely.
    """
    result = await db.execute(select(Payment).where(Payment.order_id == order.id))
    payment = result.scalar_one_or_none()

    # A row left over from a session in the other payment mode has a session id
    # the current gateway knows nothing about, so it has to be re-minted. Without
    # this, switching PAYMENTS_MODE would hand the browser a dead session - and,
    # worse, leave cf_order_id pointing at a gateway that never heard of it.
    if payment is not None and payment.payment_session_id:
        if mock.is_mock(payment.payment_session_id) == settings.payments_mock:
            return payment
        payment.payment_session_id = None

    if settings.payments_mock:
        cf_order_id = mock.cf_order_id_for(order.id)
        session_id = mock.payment_session_id_for(order.id)
    else:
        cf_order_id = cf_order_id_for(order.id)
        response = await cashfree.create_order(
            cf_order_id=cf_order_id,
            # The authoritative figure, priced server-side when the order was
            # placed. OrderCreate has no amount field and must never gain one.
            amount=order.total_amount,
            customer_id=str(order.customer_id),
            customer_name=order.customer_name,
            customer_email=order.customer.email,
            customer_phone=order.customer_phone or "",
            settings=settings,
        )
        session_id = response.get("payment_session_id")

    if payment is None:
        payment = Payment(
            order_id=order.id,
            cf_order_id=cf_order_id,
            amount=order.total_amount,
            refund_id=refund_id_for(order.id),
        )
        db.add(payment)
    else:
        # Kept in step with the session: cf_order_id is what a webhook is matched
        # on, so a row holding one mode's order id and the other's session is a
        # payment that can never be settled by anybody.
        payment.cf_order_id = cf_order_id
    payment.payment_session_id = session_id
    await db.commit()
    await db.refresh(payment)
    return payment


def _amounts_match(claimed, expected: Decimal) -> bool:
    """Compare money without letting a float in through the back door."""
    try:
        return Decimal(str(claimed)).quantize(Decimal("0.01")) == Decimal(expected).quantize(
            Decimal("0.01")
        )
    except (TypeError, ValueError, ArithmeticError):
        return False


async def apply_payment_success(
    order: Order, payment: Payment, body: dict, db: AsyncSession
) -> str:
    """Mark an order paid, if the payload says what it should.

    Returns the outcome recorded against the event. Never raises for a business
    disagreement - the caller answers 200 either way, because a retry cannot fix
    a wrong amount and Cashfree will keep sending until it gets one.
    """
    from app.modules.orders.service import allocate_token, can_transition_payment

    data = body.get("data") or {}
    cf_payment = data.get("payment") or {}
    cf_order = data.get("order") or {}

    claimed = cf_order.get("order_amount", cf_payment.get("payment_amount"))
    if not _amounts_match(claimed, payment.amount):
        # Loud, and deliberately not auto-resolved. Either somebody is probing or
        # something is badly wrong, and both want a human.
        logger.error(
            "cashfree reported %s for order %s, which we priced at %s - not marking paid",
            claimed,
            order.id,
            payment.amount,
        )
        payment.last_error = f"amount mismatch: reported {claimed}, expected {payment.amount}"
        await db.commit()
        return "amount_mismatch"

    if (cf_order.get("order_currency") or "INR") != "INR":
        payment.last_error = f"unexpected currency {cf_order.get('order_currency')}"
        await db.commit()
        return "amount_mismatch"

    if not can_transition_payment(order.payment_status, PaymentStatus.PAID):
        # Already paid, or already refunded. Recorded, not applied.
        return "rejected_transition"

    order.payment_status = PaymentStatus.PAID
    payment.cf_payment_id = str(cf_payment.get("cf_payment_id") or "") or None
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


async def apply_payment_failure(order: Order, body: dict, db: AsyncSession) -> str:
    from app.modules.orders.service import can_transition_payment

    if not can_transition_payment(order.payment_status, PaymentStatus.FAILED):
        return "rejected_transition"
    order.payment_status = PaymentStatus.FAILED
    await db.commit()
    return "applied"


async def apply_refund_update(order: Order, payment: Payment, body: dict, db: AsyncSession) -> str:
    from app.modules.orders.service import can_transition_payment

    refund = (body.get("data") or {}).get("refund") or {}
    status = str(refund.get("refund_status") or "").upper()

    target = {
        "SUCCESS": PaymentStatus.REFUNDED,
        "FAILED": PaymentStatus.REFUND_FAILED,
        "CANCELLED": PaymentStatus.REFUND_FAILED,
    }.get(status)
    if target is None:
        # PENDING or ONHOLD: nothing has changed yet.
        return "rejected_transition"

    if not can_transition_payment(order.payment_status, target):
        return "rejected_transition"

    order.payment_status = target
    if target is PaymentStatus.REFUND_FAILED:
        payment.last_error = f"refund {status.lower()}"
    await db.commit()
    return "applied"


async def start_refund(order_id: uuid.UUID, reason: str, db: AsyncSession) -> None:
    """Move an order's money state to refund-pending, without calling anybody.

    Split from the call on purpose: a stall rejecting an order must succeed while
    Cashfree is unreachable, so the state change commits inside the request and
    the network attempt happens afterwards.
    """
    from app.modules.orders.service import can_transition_payment

    order = await db.get(Order, order_id)
    if order is None or not can_transition_payment(order.payment_status, PaymentStatus.REFUND_PENDING):
        return
    order.payment_status = PaymentStatus.REFUND_PENDING

    result = await db.execute(select(Payment).where(Payment.order_id == order_id))
    payment = result.scalar_one_or_none()
    if payment is not None and not payment.refund_id:
        payment.refund_id = refund_id_for(order_id)
    await db.commit()


async def attempt_refund(order_id: uuid.UUID, reason: str, settings: Settings) -> None:
    """Actually ask Cashfree for the money back.

    Runs after the response, in its own session - the request's session is closed
    by its dependency by the time a background task runs, and reusing it fails
    only under load, which is the worst time to find out.
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
        result = await db.execute(select(Payment).where(Payment.order_id == order_id))
        payment = result.scalar_one_or_none()
        order = await db.get(Order, order_id)
        if payment is None or order is None:
            return
        if order.payment_status is not PaymentStatus.REFUND_PENDING:
            return

        payment.refund_attempts += 1
        await db.commit()

        try:
            await cashfree.refund(
                cf_order_id=payment.cf_order_id,
                refund_id=payment.refund_id or refund_id_for(order_id),
                amount=payment.amount,
                note=reason,
                settings=settings,
            )
        except Exception as exc:
            # Left in refund_pending rather than marked failed: the money is
            # still owed and the next drain should try again. The error is
            # recorded so an admin can see why it is stuck.
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
    than Cashfree's own expiry so a payment the gateway would still accept is
    never cancelled underneath it.

    The status predicate is load-bearing: an order the customer cancelled
    themselves must not be rewritten by a sweep.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=settings.cashfree_order_expiry_minutes + SWEEP_GRACE_MINUTES
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
