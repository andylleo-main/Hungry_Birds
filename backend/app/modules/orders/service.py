import secrets
import uuid

from fastapi import HTTPException, status as http_status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.order import FulfilmentType, Order, OrderStatus
from app.db.models.payment import PaymentStatus
from app.modules.orders.schemas import OrderWithCodeOut

# What an order must carry before it can be serialised.
#
# Order.customer and Order.rider are both lazy="raise" and OrderOut reads
# through both, so any query that feeds model_validate must load them here -
# otherwise serialisation raises MissingGreenlet, including inside the WebSocket
# broadcast where it is least visible. Kept in one place because four modules now
# build order queries, and the failure only shows up at serialisation time.
ORDER_LOADS = (
    selectinload(Order.items),
    selectinload(Order.customer),
    selectinload(Order.rider),
)


def order_query(*where):
    """A SELECT that produces orders safe to serialise.

    populate_existing is load-bearing, not tidiness. The session is created with
    expire_on_commit=False, so an Order already in the identity map keeps the
    relationships it loaded earlier, and re-querying it hands back that same
    stale object. That showed up as a real leak: after a merchant took a delivery
    back off a rider, the response still carried the *previous* rider's phone
    number, because Order.rider had been loaded before rider_id was cleared.
    """
    return (
        select(Order)
        .where(*where)
        .options(*ORDER_LOADS)
        .execution_options(populate_existing=True)
    )


async def load_order(order_id: uuid.UUID, db: AsyncSession) -> Order | None:
    result = await db.execute(order_query(Order.id == order_id))
    return result.scalar_one_or_none()

# Which statuses an order may move to from its current status. Anything not
# listed as a key (COMPLETED, REJECTED, CANCELLED) is terminal.
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    # Nothing but a confirmed payment moves an order out of here, and a stall
    # never sees it until it does. CANCELLED is the abandoned-checkout path.
    OrderStatus.AWAITING_PAYMENT: {OrderStatus.PLACED, OrderStatus.CANCELLED},
    OrderStatus.PLACED: {OrderStatus.ACCEPTED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.ACCEPTED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY},
    # A dine-in order is handed across the counter, so READY -> COMPLETED
    # directly. A delivery goes out with somebody first.
    OrderStatus.READY: {OrderStatus.OUT_FOR_DELIVERY, OrderStatus.COMPLETED},
    OrderStatus.OUT_FOR_DELIVERY: {OrderStatus.COMPLETED},
}

# Nothing moves out of these. Derived from the table rather than restated, so
# the two can never disagree.
TERMINAL_STATUSES = frozenset(set(OrderStatus) - set(ALLOWED_TRANSITIONS))

# Statuses that only make sense for a delivery. The transition table above says
# what order things happen in; this says which orders they apply to at all.
DELIVERY_ONLY_STATUSES = frozenset({OrderStatus.OUT_FOR_DELIVERY})

# Which payment states may follow which. Separate from the fulfilment table
# above because they describe different things, and conflating them would need a
# value for every combination of the two.
ALLOWED_PAYMENT_TRANSITIONS: dict[PaymentStatus, set[PaymentStatus]] = {
    PaymentStatus.PENDING: {PaymentStatus.PAID, PaymentStatus.FAILED, PaymentStatus.EXPIRED},
    # A customer whose card was declined can try again on the same Cashfree
    # order, so a failure is not the end.
    PaymentStatus.FAILED: {PaymentStatus.PAID},
    # And a late success after we gave up is real money arriving: it has to be
    # accepted, and then refunded, rather than asserted away. Sheet opened at
    # 12:15, swept at 12:30, paid at 12:31 happens.
    PaymentStatus.EXPIRED: {PaymentStatus.PAID},
    PaymentStatus.PAID: {PaymentStatus.REFUND_PENDING},
    PaymentStatus.REFUND_PENDING: {PaymentStatus.REFUNDED, PaymentStatus.REFUND_FAILED},
    PaymentStatus.REFUND_FAILED: {PaymentStatus.REFUND_PENDING},
}


def can_transition_payment(current: PaymentStatus, target: PaymentStatus) -> bool:
    """Whether a money state may follow another.

    This is what makes webhooks arriving out of order safe. Cashfree does not
    promise an order, and a PAYMENT_FAILED landing after a PAYMENT_SUCCESS must
    not un-pay an order - so the table refuses it and the event is recorded
    rather than applied.
    """
    return target in ALLOWED_PAYMENT_TRANSITIONS.get(current, set())


# What a rider may do to an order assigned to them: pick it up, and deliver it.
# The transition table has no notion of who is asking, and until riders existed
# it did not need one - the only caller was the stall. Kept separate rather than
# folded in, so the question "what may a rider change?" has one short answer.
RIDER_ALLOWED_TARGETS = frozenset({OrderStatus.OUT_FOR_DELIVERY, OrderStatus.COMPLETED})


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


def assert_transition(order: Order, target: OrderStatus) -> None:
    """Check a status change against both the order's history and its shape."""
    if not can_transition(order.status, target):
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            f"Cannot move an order from {order.status.value} to {target.value}",
        )
    if target in DELIVERY_ONLY_STATUSES and order.fulfilment_type is not FulfilmentType.DELIVERY:
        raise HTTPException(
            http_status.HTTP_400_BAD_REQUEST,
            f"{target.value.replace('_', ' ').capitalize()} only applies to a delivery order",
        )


# How many wrong handover codes a rider may try on one order before it stops
# accepting any. Four digits is ten thousand combinations, so this is what makes
# guessing hopeless rather than the length. Past the limit the stall completes
# the order themselves, which is an escape hatch that already existed.
MAX_DELIVERY_CODE_ATTEMPTS = 5
DELIVERY_CODE_ATTEMPT_WINDOW_SECONDS = 30 * 60


def generate_delivery_code() -> str:
    """A four-digit handover code.

    secrets rather than random: it is short, and a predictable sequence would let
    a rider close orders they never delivered.
    """
    return f"{secrets.randbelow(10_000):04d}"


def order_channel(order_id) -> str:
    return f"order:{order_id}"


def vendor_channel(vendor_id) -> str:
    return f"vendor:{vendor_id}"


async def publish_order_event(redis: Redis, order: Order) -> None:
    """Broadcast an order to whoever is entitled to hear about it.

    The asymmetry is the design. The order channel is "your order" and has no
    admission rule - a customer watching their own checkout should see it move
    to awaiting-payment and then to placed. The vendor channel is "your queue",
    and an order nobody has paid for does not belong in it.

    The payload carries the handover code, which is safe here precisely because
    riders have no channel - they poll endpoints that return the code-less
    model. If a rider channel is ever added, this must not be what feeds it.

    Putting that rule here rather than at the call sites means it cannot be
    forgotten by the next thing that publishes. It also gives a nice property for
    free: when the webhook flips an order to paid and republishes, the merchant
    app's existing update handler does not recognise the id and prepends it, so a
    newly paid order simply appears at the top of the queue with no client
    change at all.
    """
    payload = OrderWithCodeOut.model_validate(order).model_dump_json()
    await redis.publish(order_channel(order.id), payload)
    if order.payment_status == PaymentStatus.PAID:
        await redis.publish(vendor_channel(order.vendor_id), payload)
