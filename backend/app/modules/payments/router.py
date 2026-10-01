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
from app.core.deps import require_role
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
from app.modules.payments import cashfree, service
from app.modules.payments.schemas import PaymentSessionOut, WebhookAck

logger = logging.getLogger(__name__)

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
    user: User = Depends(require_role(UserRole.CUSTOMER)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PaymentSessionOut:
    """Open Cashfree checkout for an order the caller owns.

    This is the last moment before money moves, and the only place that can still
    refuse cheaply, so the things that may have changed since the order was
    created get re-checked here: the stall may have closed, or an item may have
    sold out, while the customer sat on the checkout page.

    What is deliberately *not* re-checked is the price. Lines are snapshotted at
    creation, so a menu edit changes neither what the customer pays nor what the
    stall is owed - and re-pricing here would break the one invariant protecting
    us from a forged amount, that payments.amount equals what we told Cashfree.
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
    except cashfree.CashfreeError as exc:
        logger.error("could not open a cashfree order for %s: %s", order_id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not reach the payment provider. Nothing was charged - please try again.",
        )

    if not payment.payment_session_id:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The payment provider did not answer")

    return PaymentSessionOut(
        payment_session_id=payment.payment_session_id,
        cf_order_id=payment.cf_order_id,
        mode=settings.cashfree_env,
        order_id=order.id,
    )


@router.post(
    "/cashfree/webhook",
    response_model=WebhookAck,
    # Its own bucket, and it fails OPEN - the inverse of the login routes, and
    # deliberately so. There, failing open means account takeover; here, failing
    # closed means refusing a payment notification and losing track of money
    # somebody has already handed over.
    dependencies=[
        Depends(limit_by_ip("cashfree_webhook", *limits.PAYMENT_WEBHOOK_PER_IP, fail_open=True))
    ],
)
async def cashfree_webhook(
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> WebhookAck:
    """Cashfree telling us what happened to a payment.

    Unauthenticated by necessity and signature-verified in consequence. Note the
    body is read raw and parsed here rather than declared as a Pydantic model:
    the signature covers the exact bytes Cashfree sent, and re-serialising a
    parsed payload changes key order and whitespace, so verification would never
    match.

    Everything durably recorded answers 200, including things we decline to act
    on. A non-2xx is a request to retry, and Cashfree will keep asking - so
    returning 500 for a business disagreement produces a retry storm that cannot
    possibly succeed.
    """
    if not settings.payments_enabled:
        # Nothing can be verified, so behave as though the route does not exist
        # rather than advertising an endpoint that accepts unchecked payloads.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    raw = await request.body()
    timestamp = request.headers.get("x-webhook-timestamp", "")
    signature = request.headers.get("x-webhook-signature", "")

    if not cashfree.verify_webhook(
        raw_body=raw, timestamp=timestamp, signature=signature, settings=settings
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad signature")

    try:
        body = cashfree.parse_body(raw)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed body")

    event_type = str(body.get("type") or "UNKNOWN")
    event_id = service.event_id_for(body, timestamp, raw)

    # The idempotency guard, written in the same transaction as the state change
    # it authorises - so a rollback releases it too, and Cashfree's retry is not
    # silently swallowed with the money left unbooked.
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

    cf_order_id = ((body.get("data") or {}).get("order") or {}).get("order_id", "")
    order_id = service.order_id_from_cf(str(cf_order_id))
    if order_id is None:
        event.outcome = "unknown_order"
        await db.commit()
        logger.warning("cashfree webhook for an order id we do not recognise: %r", cf_order_id)
        return WebhookAck(status="ignored")

    result = await db.execute(
        select(Payment).where(Payment.order_id == order_id).with_for_update()
    )
    payment = result.scalar_one_or_none()
    order = await load_order(order_id, db)
    if payment is None or order is None:
        event.outcome = "unknown_order"
        await db.commit()
        return WebhookAck(status="ignored")

    event.payment_id = payment.id

    if event_type.startswith("PAYMENT_SUCCESS"):
        outcome = await service.apply_payment_success(order, payment, body, db)
    elif event_type.startswith(("PAYMENT_FAILED", "PAYMENT_USER_DROPPED")):
        outcome = await service.apply_payment_failure(order, body, db)
    elif event_type.startswith("REFUND"):
        outcome = await service.apply_refund_update(order, payment, body, db)
    else:
        outcome = "ignored"

    event.outcome = outcome
    await db.commit()

    if outcome == "applied" and event_type.startswith("PAYMENT_SUCCESS"):
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

    return WebhookAck(status=outcome)


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
