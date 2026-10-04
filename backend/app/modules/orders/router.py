import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.config import Settings, get_settings
from app.core.deps import ORDERING_ROLES, get_current_user, require_role
from app.core.ratelimit import limit_by_user
from app.core.redis import get_redis
from app.db.models.menu import MenuItem
from app.db.models.order import FulfilmentType, Order, OrderItem, OrderStatus
from app.db.models.payment import PaymentStatus
from app.db.models.rider import Rider
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.orders.schemas import (
    OrderAssign,
    OrderCreate,
    OrderStatusUpdate,
    OrderWithCodeOut,
)
from app.modules.auth.service import assert_allowed_domain
from app.core.tasks import fire_and_log
from app.modules.fulfilment.service import assert_order_fulfilment
from app.modules.notifications.service import notify_new_order, notify_rider_assigned
from app.modules.payments import service as payments
from app.modules.orders.service import (
    REFUNDABLE_ENDINGS,
    TERMINAL_STATUSES,
    assert_transition,
    generate_delivery_code,
    generate_order_number,
    load_order,
    may_view_order,
    order_query,
    publish_order_event,
)
from app.modules.menu.service import resolve_line_price
from app.modules.vendors.deps import get_own_vendor

router = APIRouter(prefix="/orders", tags=["orders"])
vendor_orders_router = APIRouter(prefix="/vendors/me/orders", tags=["orders"])


# Kept as a local alias: every call site in this module already reads
# _load_order_with_items, and the behaviour now lives in the service beside the
# eager-load tuple it depends on.
_load_order_with_items = load_order


@router.post(
    "",
    response_model=OrderWithCodeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_user("place_order", *limits.PLACE_ORDER))],
)
async def place_order(
    payload: OrderCreate,
    background: BackgroundTasks,
    user: User = Depends(require_role(*ORDERING_ROLES)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> OrderWithCodeOut:
    """Place an order.

    Customers only. That gate is new, and it is the rule that keeps ordering
    inside the institute now that a stall may register with any email address on
    the internet: a vendor account is not a customer account, so it cannot
    spend. Previously any signed-in user could order, which was harmless only
    because every account had had to prove an institute address to exist at all.

    The domain is re-checked below as well. A customer can only be created
    through the institute-only login route, so this is belt and braces - but it
    is the difference between the campus restriction being a property of *this
    endpoint* and it being an accident of how accounts happen to be made today.
    """
    assert_allowed_domain(user.email, settings, action="place an order")

    # Refuse up front rather than creating something that can never complete.
    # Payment is the only route out of awaiting_payment, so without a configured
    # gateway an accepted order would sit forever: the customer gets a
    # confirmation, the stall never sees it, and nothing anywhere says why.
    if not settings.payments_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Online payments are not set up yet, so orders can't be taken. Please try later.",
        )

    vendor = await db.get(Vendor, payload.vendor_id)
    if vendor is None or not vendor.is_approved:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")
    if not vendor.is_open:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This vendor is currently closed")

    # The stall - or the rider carrying it to a hostel - has to be able to reach
    # the customer, so a phone number is a hard requirement to place an order.
    if not user.phone:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Add a phone number to your profile so the stall can reach you about your order.",
        )

    await assert_order_fulfilment(
        vendor, payload.fulfilment_type, payload.delivery_location, db
    )

    order = Order(
        customer_id=user.id,
        vendor_id=vendor.id,
        note=payload.note,
        total_amount=0,
        # Drawn at creation, unlike the token number: this is how an order is
        # referred to in support and on a refund, so it has to exist from the
        # moment the row does - including for an order nobody ever pays for.
        order_number=await generate_order_number(db),
        fulfilment_type=payload.fulfilment_type,
        delivery_location=payload.delivery_location,
        # Only a delivery changes hands away from the counter, so only a
        # delivery needs proof that it did.
        delivery_code=(
            generate_delivery_code()
            if payload.fulfilment_type is FulfilmentType.DELIVERY
            else None
        ),
    )
    # One query for every line, rather than one per line. Two reasons beyond the
    # round trips: the stall's own items are fetched whether or not they are
    # available, so a sold-out dish can be named rather than described by id;
    # and every line is checked before anything is refused, so a cart with three
    # sold-out dishes says so once instead of over three attempts.
    #
    # Scoped to this vendor, so an item id belonging to another stall simply is
    # not found. That is deliberate: answering with a name would turn this into
    # a way to read another stall's menu by guessing ids.
    found = {
        item.id: item
        for item in (
            await db.execute(
                select(MenuItem).where(
                    MenuItem.id.in_({line.menu_item_id for line in payload.items}),
                    MenuItem.vendor_id == vendor.id,
                )
            )
        ).scalars()
    }

    # Sizes, keyed by id, but only ones belonging to the items above - so a
    # crafted payload cannot pair a cheap size with an expensive dish, or borrow
    # a size from another stall's menu. The ownership chain is item -> vendor,
    # already proved by the query above, then variant -> item here.
    variants = {v.id: v for item in found.values() for v in item.variants}

    unavailable = []
    for line in payload.items:
        menu_item = found.get(line.menu_item_id)
        variant = variants.get(line.variant_id) if line.variant_id else None
        gone = (
            menu_item is None
            or not menu_item.is_available
            # A size that is not this dish's is not a size at all.
            or (line.variant_id is not None and (variant is None or variant.item_id != menu_item.id))
            or (variant is not None and not variant.is_available)
        )
        if gone:
            name = menu_item.name if menu_item is not None else None
            if name is not None and variant is not None:
                name = f"{name} ({variant.name})"
            unavailable.append(
                {
                    "menu_item_id": str(line.menu_item_id),
                    # None where the stall has deleted the dish outright. The
                    # client falls back to "an item" rather than printing a UUID.
                    "name": name,
                }
            )

    if unavailable:
        # A structured body, not a sentence. This used to interpolate the raw
        # UUID into the message, and the web app rendered it verbatim - so a
        # customer whose dish sold out mid-checkout was shown
        # "Menu item 3f8a1c2e-9b44-... is not available from this vendor".
        # The client needs the ids to strike the right lines through, and the
        # names to say which dishes, so it gets both and writes its own wording.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "items_unavailable",
                "message": "Some items are no longer available",
                "items": unavailable,
            },
        )

    total = 0
    for line in payload.items:
        menu_item = found[line.menu_item_id]
        variant = variants.get(line.variant_id) if line.variant_id else None
        # The one place that knows a dish can be priced two ways, and the only
        # thing that decides what a line costs. The price comes off the row the
        # server read, never off the payload.
        unit = resolve_line_price(menu_item, variant)
        total += unit * line.quantity
        order.items.append(
            OrderItem(
                menu_item_id=menu_item.id,
                variant_id=variant.id if variant else None,
                name_snapshot=menu_item.name,
                variant_name_snapshot=variant.name if variant else None,
                price_snapshot=unit,
                quantity=line.quantity,
            )
        )

    order.total_amount = total
    db.add(order)
    await db.commit()

    order = await _load_order_with_items(order.id, db)
    # Published to the customer's own channel only - publish_order_event will not
    # touch the stall's queue for an unpaid order, and nobody is notified yet.
    # The stall first hears about this when the payment webhook lands.
    await publish_order_event(redis, order)
    return OrderWithCodeOut.model_validate(order)


@router.get(
    "",
    response_model=list[OrderWithCodeOut],
    dependencies=[Depends(limit_by_user("order_read", *limits.ORDER_READ))],
)
async def list_my_orders(
    background: BackgroundTasks,
    user: User = Depends(require_role(*ORDERING_ROLES)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[OrderWithCodeOut]:
    # No scheduler exists in this project, so the sweep rides on the read that
    # would otherwise display these rows. Cheap: it touches only this customer's
    # abandoned checkouts, and only ones older than the gateway's own expiry.
    await payments.sweep_abandoned(db, settings, customer_id=user.id)
    # And the same trick for refunds that were started and never finished. This
    # is the page somebody waiting on their money refreshes, so it is the right
    # read to hang the retry on.
    await payments.drain_stuck_refunds(db, settings, background, customer_id=user.id)

    result = await db.execute(
        order_query(Order.customer_id == user.id).order_by(Order.created_at.desc())
    )
    return [OrderWithCodeOut.model_validate(o) for o in result.scalars().all()]


async def _get_order_for_user(order_id: uuid.UUID, user: User, db: AsyncSession) -> Order:
    order = await _load_order_with_items(order_id, db)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    # Shared with the order WebSocket, which used to carry its own slightly
    # different copy of this rule. The customer keeps seeing their own unpaid
    # order so the tracking page can tell them to finish paying; the stall has no
    # business with it until it is paid.
    if not await may_view_order(order, user, db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


@router.get(
    "/{order_id}",
    response_model=OrderWithCodeOut,
    dependencies=[Depends(limit_by_user("order_read", *limits.ORDER_READ))],
)
async def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderWithCodeOut:
    order = await _get_order_for_user(order_id, user, db)
    return OrderWithCodeOut.model_validate(order)


@vendor_orders_router.get(
    "",
    response_model=list[OrderWithCodeOut],
    dependencies=[Depends(limit_by_user("order_read", *limits.ORDER_READ))],
)
async def list_vendor_orders(
    background: BackgroundTasks,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[OrderWithCodeOut]:
    """The stall's queue - which contains only orders somebody has paid for.

    The socket filter alone is not enough: it covers what happens while the app
    is open, and the merchant app re-fetches this on every start and every
    reconnect. Without the same rule here, an abandoned checkout would reappear
    in the queue every time the connection blinked.
    """
    await payments.sweep_abandoned(db, settings, vendor_id=vendor.id)
    await payments.drain_stuck_refunds(db, settings, background, vendor_id=vendor.id)

    result = await db.execute(
        order_query(
            Order.vendor_id == vendor.id,
            Order.status != OrderStatus.AWAITING_PAYMENT,
        ).order_by(Order.created_at.desc())
    )
    return [OrderWithCodeOut.model_validate(o) for o in result.scalars().all()]


@vendor_orders_router.patch(
    "/{order_id}/status",
    response_model=OrderWithCodeOut,
    dependencies=[Depends(limit_by_user("order_status", *limits.ORDER_STATUS_UPDATE))],
)
async def update_order_status(
    order_id: uuid.UUID,
    payload: OrderStatusUpdate,
    background: BackgroundTasks,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> OrderWithCodeOut:
    order = await _load_order_with_items(order_id, db)
    if order is None or order.vendor_id != vendor.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    assert_transition(order, payload.status)

    order.status = payload.status
    await db.commit()

    # A stall ending an order without the customer getting their food is the
    # customer's money coming back. The state change commits here and the call to
    # Cashfree happens after the response, so a gateway outage cannot make
    # refusing an order fail - the stall must never be stuck with an order they
    # cannot refuse because somebody else's server is down.
    #
    # This used to check REJECTED alone, while the transition table has always
    # allowed CANCELLED from both PLACED and ACCEPTED. A stall that sent
    # cancelled on a paid order therefore closed it and kept the money, silently
    # and with nothing in any log to say so. Asking REFUNDABLE_ENDINGS instead of
    # naming statuses is what stops the next terminal status repeating it.
    if payload.status in REFUNDABLE_ENDINGS and order.payment_status is PaymentStatus.PAID:
        reason = (
            "stall could not make this order"
            if payload.status is OrderStatus.REJECTED
            else "stall cancelled this order"
        )
        await payments.start_refund(order.id, reason, db)
        background.add_task(
            fire_and_log,
            "refund_refused_order",
            lambda: payments.attempt_refund(order.id, reason, settings),
        )

    order = await _load_order_with_items(order.id, db)
    await publish_order_event(redis, order)
    return OrderWithCodeOut.model_validate(order)


@vendor_orders_router.post(
    "/{order_id}/assign",
    response_model=OrderWithCodeOut,
    dependencies=[Depends(limit_by_user("order_assign", *limits.ORDER_ASSIGN))],
)
async def assign_order(
    order_id: uuid.UUID,
    payload: OrderAssign,
    background: BackgroundTasks,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> OrderWithCodeOut:
    """Send a delivery out with one of your riders, or take it yourself.

    Assigning is what releases the customer's phone number to the rider, and what
    gives the customer a number to call. It does not move the order's status: a
    merchant usually assigns while the food is still being made, and having that
    jump the order to "out for delivery" would tell the customer it had left
    before it had.
    """
    order = await _load_order_with_items(order_id, db)
    if order is None or order.vendor_id != vendor.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    if order.fulfilment_type is not FulfilmentType.DELIVERY:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Only a delivery order needs someone to carry it"
        )
    if order.status in TERMINAL_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "This order is finished and cannot be reassigned"
        )

    if payload.rider_id is not None:
        # Scoped to this stall's riders, and 404 rather than 403 - the same shape
        # the menu routes use, so probing cannot map another stall's rider ids.
        result = await db.execute(
            select(Rider).where(
                Rider.id == payload.rider_id,
                Rider.vendor_id == vendor.id,
            )
        )
        rider = result.scalar_one_or_none()
        if rider is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Rider not found")
        if not rider.is_active:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"{rider.display_name} is no longer active"
            )
        order.rider_id = rider.id
        order.self_delivery = False
    else:
        order.rider_id = None
        order.self_delivery = payload.self_delivery

    await db.commit()
    order = await _load_order_with_items(order.id, db)
    await publish_order_event(redis, order)

    # The rider app polls, so this is not how they learn about it - it is how
    # they learn while the phone is in their pocket. Best-effort, after the
    # response: a merchant assigning an order must not wait on Firebase, or fail
    # because of it.
    if order.rider_id is not None:
        assigned_to = order.rider_id
        background.add_task(
            fire_and_log,
            "notify_rider_assigned",
            lambda: notify_rider_assigned(order.id, assigned_to, settings),
        )
    return OrderWithCodeOut.model_validate(order)
