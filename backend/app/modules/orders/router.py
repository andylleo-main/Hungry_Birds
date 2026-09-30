import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import limits
from app.core.config import Settings, get_settings
from app.core.deps import get_current_user, require_role
from app.core.ratelimit import limit_by_user
from app.core.redis import get_redis
from app.db.models.menu import MenuItem
from app.db.models.order import Order, OrderItem, OrderStatus
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.orders.schemas import OrderCreate, OrderOut, OrderStatusUpdate
from app.modules.auth.service import assert_allowed_domain
from app.modules.fulfilment.service import assert_order_fulfilment
from app.modules.orders.service import can_transition, publish_order_event
from app.modules.vendors.deps import get_own_vendor

router = APIRouter(prefix="/orders", tags=["orders"])
vendor_orders_router = APIRouter(prefix="/vendors/me/orders", tags=["orders"])


async def _load_order_with_items(order_id: uuid.UUID, db: AsyncSession) -> Order | None:
    result = await db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items), selectinload(Order.customer))
    )
    return result.scalar_one_or_none()


@router.post(
    "",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_user("place_order", *limits.PLACE_ORDER))],
)
async def place_order(
    payload: OrderCreate,
    user: User = Depends(require_role(UserRole.CUSTOMER)),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> OrderOut:
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
        fulfilment_type=payload.fulfilment_type,
        delivery_location=payload.delivery_location,
    )
    total = 0
    for line in payload.items:
        result = await db.execute(
            select(MenuItem).where(
                MenuItem.id == line.menu_item_id,
                MenuItem.vendor_id == vendor.id,
                MenuItem.is_available.is_(True),
            )
        )
        menu_item = result.scalar_one_or_none()
        if menu_item is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Menu item {line.menu_item_id} is not available from this vendor",
            )
        line_total = menu_item.price * line.quantity
        total += line_total
        order.items.append(
            OrderItem(
                menu_item_id=menu_item.id,
                name_snapshot=menu_item.name,
                price_snapshot=menu_item.price,
                quantity=line.quantity,
            )
        )

    order.total_amount = total
    db.add(order)
    await db.commit()

    order = await _load_order_with_items(order.id, db)
    await publish_order_event(redis, order)
    return OrderOut.model_validate(order)


@router.get(
    "",
    response_model=list[OrderOut],
    dependencies=[Depends(limit_by_user("order_read", *limits.ORDER_READ))],
)
async def list_my_orders(
    user: User = Depends(require_role(UserRole.CUSTOMER)), db: AsyncSession = Depends(get_db)
) -> list[OrderOut]:
    result = await db.execute(
        select(Order)
        .where(Order.customer_id == user.id)
        .options(selectinload(Order.items), selectinload(Order.customer))
        .order_by(Order.created_at.desc())
    )
    return [OrderOut.model_validate(o) for o in result.scalars().all()]


async def _get_order_for_user(order_id: uuid.UUID, user: User, db: AsyncSession) -> Order:
    order = await _load_order_with_items(order_id, db)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    is_owner_customer = order.customer_id == user.id
    is_owner_vendor = False
    if user.role == UserRole.VENDOR:
        result = await db.execute(select(Vendor).where(Vendor.user_id == user.id))
        vendor = result.scalar_one_or_none()
        is_owner_vendor = vendor is not None and vendor.id == order.vendor_id

    if not (is_owner_customer or is_owner_vendor or user.role == UserRole.ADMIN):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


@router.get(
    "/{order_id}",
    response_model=OrderOut,
    dependencies=[Depends(limit_by_user("order_read", *limits.ORDER_READ))],
)
async def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    order = await _get_order_for_user(order_id, user, db)
    return OrderOut.model_validate(order)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderOut,
    dependencies=[Depends(limit_by_user("cancel_order", *limits.CANCEL_ORDER))],
)
async def cancel_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> OrderOut:
    order = await _get_order_for_user(order_id, user, db)
    if order.customer_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the customer can cancel this order")
    if not can_transition(order.status, OrderStatus.CANCELLED):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Cannot cancel an order that is already {order.status.value}"
        )
    order.status = OrderStatus.CANCELLED
    await db.commit()
    order = await _load_order_with_items(order.id, db)
    await publish_order_event(redis, order)
    return OrderOut.model_validate(order)


@vendor_orders_router.get(
    "",
    response_model=list[OrderOut],
    dependencies=[Depends(limit_by_user("order_read", *limits.ORDER_READ))],
)
async def list_vendor_orders(
    vendor: Vendor = Depends(get_own_vendor), db: AsyncSession = Depends(get_db)
) -> list[OrderOut]:
    result = await db.execute(
        select(Order)
        .where(Order.vendor_id == vendor.id)
        .options(selectinload(Order.items), selectinload(Order.customer))
        .order_by(Order.created_at.desc())
    )
    return [OrderOut.model_validate(o) for o in result.scalars().all()]


@vendor_orders_router.patch(
    "/{order_id}/status",
    response_model=OrderOut,
    dependencies=[Depends(limit_by_user("order_status", *limits.ORDER_STATUS_UPDATE))],
)
async def update_order_status(
    order_id: uuid.UUID,
    payload: OrderStatusUpdate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> OrderOut:
    order = await _load_order_with_items(order_id, db)
    if order is None or order.vendor_id != vendor.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    if not can_transition(order.status, payload.status):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Cannot move an order from {order.status.value} to {payload.status.value}",
        )

    order.status = payload.status
    await db.commit()
    order = await _load_order_with_items(order.id, db)
    await publish_order_event(redis, order)
    return OrderOut.model_validate(order)
