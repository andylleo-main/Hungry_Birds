import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.config import Settings, get_settings
from app.core.deps import ORDERING_ROLES, require_role
from app.core.ratelimit import limit_by_ip, limit_by_user
from app.core.redis import get_redis
from app.core.tasks import fire_and_log
from app.db.models.order import Order, OrderStatus
from app.db.models.payment import Payment, PaymentEvent, PaymentStatus
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.notifications.service import notify_new_order
from app.modules.orders.service import load_order, publish_order_event
from app.modules.payments import mock, razorpay, service
from app.modules.payments.schemas import PaymentCallback, PaymentSessionOut, WebhookAck

logger = logging.getLogger(__name__)

# The events this webhook acts on. Everything else Razorpay sends is
# acknowledged and dropped.
#
# order.paid and payment.authorized are deliberately absent: both describe a
# payment that payment.captured describes again, and two paths to the same
# transition is two chances to disagree about it. qr_code.created and
# qr_code.closed are absent because they say nothing about money - only
# qr_code.credited does.
#
# If a collection never marks itself paid, check this set against the events
# actually ticked on the webhook in the Razorpay dashboard. A subscription
# missing qr_code.credited mints QR codes perfectly and never confirms one.
HANDLED_EVENTS = frozenset(
    {
        "payment.captured",
        "payment.failed",
        "refund.processed",
        "refund.failed",
        "qr_code.credited",
    }
)

router = APIRouter(prefix="/payments", tags=["payments"])

# Mounted on the order so it reads as part of checkout rather than a separate
# concept the client has to assemble.
order_payments_router = APIRouter(prefix="/orders", tags=["payments"])


@order_payments_router.post(
    "/{order_id}/payment-session",
    response_model=PaymentSessionOut,
    dependencies=[Depends(limit_by_user("payment_session", *limits.PAYMENT_SESSION))],
)
async def create_payment_session(
    order_id: uuid.UUID,
    user: User = Depends(require_role(*ORDERING_ROLES)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PaymentSessionOut:
    """Open Razorpay Checkout for an order the caller owns.

    This is the last moment before money moves, and the only place that can still
    refuse cheaply, so the things that may have changed since the order was
    created get re-checked here: the stall may have closed, or an item may have
    sold out, while the customer sat on the checkout page.

    What is deliberately *not* re-checked is the price. Lines are snapshotted at
    creation, so a menu edit changes neither what the customer pays nor what the
    stall is owed - and re-pricing here would break the one invariant protecting
    us from a forged amount, that payments.amount equals what we told the
    gateway.
    """
    if not settings.payments_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Online payments are not configured yet"
        )

    order = await load_order(order_id, db)
    if order is None or order.customer_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order.payment_status is PaymentStatus.PAID:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This order is already paid for")
    if order.status not in (OrderStatus.AWAITING_PAYMENT,):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This order can no longer be paid for")

    vendor = await db.get(Vendor, order.vendor_id)
    if vendor is None or not vendor.is_approved:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This stall is no longer available")
    if not vendor.is_open:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This stall has closed. Nothing was charged.")

    try:
        payment = await service.ensure_payment(order, db, settings)
    except razorpay.RazorpayError as exc:
        logger.error("could not open a razorpay order for %s: %s", order_id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not reach the payment provider. Nothing was charged - please try again.",
        )

    if not payment.gateway_order_id:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The payment provider did not answer")

    return PaymentSessionOut(
        gateway_order_id=payment.gateway_order_id,
        key_id=settings.razorpay_key_id,
        amount=razorpay.to_paise(payment.amount),
        currency=payment.currency,
        # "mock" is how the browser knows to skip Checkout and call the confirm
        # route below instead. It doubles as the flag the checkout page shows a
        # banner for, so a tester is never left guessing whether a payment was
        # real.
        mode="mock" if settings.payments_mock else "razorpay",
        order_id=order.id,
    )


@order_payments_router.post(
    "/{order_id}/mock-payment",
    response_model=WebhookAck,
    dependencies=[Depends(limit_by_user("payment_session", *limits.PAYMENT_SESSION))],
)
async def confirm_mock_payment(
    order_id: uuid.UUID,
    background: BackgroundTasks,
    user: User = Depends(require_role(*ORDERING_ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> WebhookAck:
    """Stand in for the customer paying, when PAYMENTS_MODE=mock.

    Exists so the whole flow after a payment can be walked through without
    gateway credentials. It does not short-circuit anything: it builds the
    payment entity Razorpay would have sent, runs it through the same
    apply_payment_success - amount check included - and the same side effects the
    webhook triggers.

    Unlike that webhook this route is authenticated and ownership-checked, which
    is the strongest thing available here. A route that marks an order paid for
    free cannot be made safe by its own checks, so what keeps it harmless is that
    it 404s unless somebody has deliberately set PAYMENTS_MODE=mock.
    """
    if not settings.payments_mock:
        # Not a 403: in real-payment mode this endpoint should not appear to
        # exist at all. Advertising a disabled "mark as paid" route is an
        # invitation to go looking for a way to turn it on.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    order = await load_order(order_id, db)
    if order is None or order.customer_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    result = await db.execute(
        select(Payment).where(Payment.order_id == order_id).with_for_update()
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        # No payment-session call came first, so there is nothing to confirm.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This order has no payment to confirm")

    entity = mock.success_entity(
        gateway_order_id=payment.gateway_order_id, amount=payment.amount
    )
    event_id = f"{mock.EVENT_TYPE}:{entity['id']}"

    # The same ledger the real webhook writes, for the same reason - and it is
    # what makes an order that was never really paid for identifiable later,
    # however long after the fact.
    event = PaymentEvent(
        event_id=event_id,
        event_type=mock.EVENT_TYPE,
        raw=_jsonable(entity),
        received_at=datetime.now(timezone.utc),
        payment_id=payment.id,
    )
    db.add(event)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return WebhookAck(status="duplicate")

    outcome = await service.apply_payment_success(order, payment, entity, db)
    event.outcome = outcome
    await db.commit()

    if outcome == "applied":
        await _after_payment_success(order_id, db, redis, background, settings)

    return WebhookAck(status=outcome)


@order_payments_router.post(
    "/{order_id}/payment-callback",
    response_model=WebhookAck,
    dependencies=[Depends(limit_by_user("payment_session", *limits.PAYMENT_SESSION))],
)
async def payment_callback(
    order_id: uuid.UUID,
    payload: PaymentCallback,
    background: BackgroundTasks,
    user: User = Depends(require_role(*ORDERING_ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> WebhookAck:
    """Confirm a payment from what Checkout handed back to the page.

    Insurance, not the primary path. The webhook remains authoritative and this
    route exists because of what happens when it is misconfigured: without it, a
    wrong URL or a mistyped signing secret in the Razorpay dashboard means *no
    payment is ever confirmed*, every order sits unpaid, and no stall sees
    anything. That is a silent, total failure, and a launch is exactly when it
    happens.

    It is a second door to "paid", so it is held to the same standard as the
    first. The signature proves Razorpay issued this payment against this order.
    Everything that actually matters - the amount, and whether the money was
    captured rather than merely authorised - is then read from Razorpay's API
    rather than from the page, because the page is the customer's to edit. And it
    writes the same ledger row, so the webhook arriving afterwards finds the
    transition already made and records itself as a no-op.
    """
    if not settings.razorpay_configured:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    order = await load_order(order_id, db)
    if order is None or order.customer_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    result = await db.execute(
        select(Payment).where(Payment.order_id == order_id).with_for_update()
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This order has no payment to confirm")

    if payload.razorpay_order_id != payment.gateway_order_id:
        # Signed, but for a different order. Somebody is replaying one payment
        # against another order, which is the whole reason the order id is inside
        # the signed string.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That payment is for a different order")

    if not razorpay.verify_checkout_signature(
        gateway_order_id=payload.razorpay_order_id,
        payment_id=payload.razorpay_payment_id,
        signature=payload.razorpay_signature,
        settings=settings,
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad signature")

    try:
        entity = await razorpay.fetch_payment(payload.razorpay_payment_id, settings)
    except razorpay.RazorpayError as exc:
        logger.error("could not read payment %s: %s", payload.razorpay_payment_id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Could not confirm that payment. Check your orders."
        )

    if str(entity.get("status")) != "captured":
        # Authorised but not captured, or failed. The webhook will say so when it
        # settles; nothing is marked paid on a maybe.
        return WebhookAck(status="ignored")

    event = PaymentEvent(
        event_id=f"checkout:{payload.razorpay_payment_id}",
        event_type="checkout.callback",
        raw=_jsonable(entity),
        received_at=datetime.now(timezone.utc),
        payment_id=payment.id,
    )
    db.add(event)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return WebhookAck(status="duplicate")

    outcome = await service.apply_payment_success(order, payment, entity, db)
    event.outcome = outcome
    await db.commit()

    if outcome == "applied":
        await _after_payment_success(order_id, db, redis, background, settings)

    return WebhookAck(status=outcome)


@router.post(
    "/razorpay/webhook",
    response_model=WebhookAck,
    # Its own bucket, and it fails OPEN - the inverse of the login routes, and
    # deliberately so. There, failing open means account takeover; here, failing
    # closed means refusing a payment notification and losing track of money
    # somebody has already handed over.
    dependencies=[
        Depends(limit_by_ip("razorpay_webhook", *limits.PAYMENT_WEBHOOK_PER_IP, fail_open=True))
    ],
)
async def razorpay_webhook(
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> WebhookAck:
    """Razorpay telling us what happened to a payment.

    Unauthenticated by necessity and signature-verified in consequence. Note the
    body is read raw and parsed here rather than declared as a Pydantic model:
    the signature covers the exact bytes Razorpay sent, and re-serialising a
    parsed payload changes key order and whitespace, so verification would never
    match.

    Everything durably recorded answers 200, including things we decline to act
    on. A non-2xx is a request to retry, and Razorpay will keep asking for 24
    hours - so returning 500 for a business disagreement produces a retry storm
    that cannot possibly succeed.
    """
    if not settings.razorpay_webhook_configured:
        # Gated on the webhook signing secret specifically, NOT on payments being
        # enabled and not on the API credentials. That secret is the only thing
        # between this open POST endpoint and anybody on the internet marking any
        # order paid, and it can legitimately be absent while the API keys are
        # present - credentials usually land before somebody registers the
        # webhook. Behave as though the route does not exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    raw = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")

    if not razorpay.verify_webhook(raw_body=raw, signature=signature, settings=settings):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad signature")

    try:
        body = razorpay.parse_body(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed body")

    event_type = str(body.get("event") or "unknown")
    event_id = service.event_id_for(body, raw, request.headers.get("x-razorpay-event-id"))

    # The idempotency guard, written in the same transaction as the state change
    # it authorises - so a rollback releases it too, and Razorpay's retry is not
    # silently swallowed with the money left unbooked.
    #
    # It carries more weight here than under Cashfree, which signed a timestamp
    # we could reject a stale replay by. Razorpay sends none, so this row is the
    # only replay protection there is.
    event = PaymentEvent(
        event_id=event_id,
        event_type=event_type,
        raw=_jsonable(body),
        received_at=datetime.now(timezone.utc),
    )
    db.add(event)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return WebhookAck(status="duplicate")

    entities = body.get("payload") or {}
    payment_entity = (entities.get("payment") or {}).get("entity") or {}
    refund_entity = (entities.get("refund") or {}).get("entity") or {}
    qr_entity = (entities.get("qr_code") or {}).get("entity") or {}

    # Anything we do not act on leaves here, before any lookup.
    #
    # Not an optimisation. A Razorpay webhook is usually subscribed to whole
    # families of events, so qr_code.created and qr_code.closed arrive every
    # time a QR is minted or replaced. Those carry no payment entity, so they
    # used to fall through to the lookup below and be logged as
    # "razorpay qr_code.created for an order we do not recognise: ''" - which is
    # not what happened, and which buried the warning that means something. A
    # genuine unrecognised order is now the only thing that logs it.
    if event_type not in HANDLED_EVENTS:
        event.outcome = "ignored"
        await db.commit()
        return WebhookAck(status="ignored")

    # A doorstep UPI collection is the one event with no payments row behind it -
    # a pay-on-delivery order never opened anything at the gateway - so it is
    # matched on the QR whoever is carrying the order is holding up instead.
    if event_type == "qr_code.credited":
        order = (
            await db.execute(select(Order).where(Order.cod_qr_id == str(qr_entity.get("id") or "")))
        ).scalar_one_or_none()
        if order is None:
            event.outcome = "unknown_order"
            await db.commit()
            return WebhookAck(status="ignored")

        outcome = await service.apply_cod_upi_collected(order, payment_entity, db)
        event.outcome = outcome
        await db.commit()
        if outcome == "applied":
            await publish_order_event(redis, await load_order(order.id, db))
        return WebhookAck(status=outcome)

    payment = None
    gateway_order_id = str(payment_entity.get("order_id") or "")
    if gateway_order_id:
        payment = await service.payment_for_gateway_order(gateway_order_id, db)
    elif refund_entity.get("payment_id"):
        # Some refund events carry no payment entity. The refund knows which
        # payment it reverses, and we recorded that id when the payment landed.
        payment = (
            await db.execute(
                select(Payment).where(
                    Payment.gateway_payment_id == str(refund_entity["payment_id"])
                )
            )
        ).scalar_one_or_none()

    if payment is None:
        event.outcome = "unknown_order"
        await db.commit()
        logger.warning("razorpay %s for an order we do not recognise: %r", event_type, gateway_order_id)
        return WebhookAck(status="ignored")

    # Re-read under a lock now that we know which row it is.
    locked = await db.execute(
        select(Payment).where(Payment.id == payment.id).with_for_update()
    )
    payment = locked.scalar_one()
    order = await load_order(payment.order_id, db)
    if order is None:
        event.outcome = "unknown_order"
        await db.commit()
        return WebhookAck(status="ignored")

    event.payment_id = payment.id

    if event_type == "payment.captured":
        outcome = await service.apply_payment_success(order, payment, payment_entity, db)
    elif event_type == "payment.failed":
        outcome = await service.apply_payment_failure(order, payment_entity, db)
    elif event_type in ("refund.processed", "refund.failed"):
        outcome = await service.apply_refund_update(order, payment, refund_entity, db)
    else:
        # Everything else Razorpay sends, including order.paid and
        # payment.authorized. Both describe a payment that payment.captured will
        # describe again, and two paths to the same transition is two chances to
        # disagree about it.
        outcome = "ignored"

    event.outcome = outcome
    await db.commit()

    if outcome == "applied" and event_type == "payment.captured":
        await _after_payment_success(order.id, db, redis, background, settings)

    return WebhookAck(status=outcome)


async def _after_payment_success(
    order_id: uuid.UUID,
    db: AsyncSession,
    redis: Redis,
    background: BackgroundTasks,
    settings: Settings,
) -> None:
    """Everything that happens once an order is actually paid for.

    Shared by the webhook, the checkout callback and the mock confirmation, so
    the three cannot drift. That matters more than the duplication it saves: the
    whole reason mock mode exists is to exercise this path, and a mock that ran
    its own cut-down version of it would test nothing worth testing.
    """
    order = await load_order(order_id, db)
    await publish_order_event(redis, order)

    if order.status == OrderStatus.PLACED:
        # The moment the stall first learns of it.
        background.add_task(
            fire_and_log,
            "notify_new_order",
            lambda: notify_new_order(order.id, order.vendor_id, settings),
        )
    elif order.status in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
        # Money arriving for an order we already gave up on. A designed path,
        # not an error: the sheet was open when the sweep ran. Give it back.
        await service.start_refund(order.id, "order already closed", db)
        background.add_task(
            fire_and_log,
            "refund_late_payment",
            lambda: service.attempt_refund(order.id, "order already closed", settings),
        )


def _jsonable(value):
    """Decimals survive the money parsing but not JSONB, so stringify them."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value
