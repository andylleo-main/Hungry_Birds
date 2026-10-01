"""What gets pushed to a stall, and when.

One notification exists today: a new order arrived. It fires at the moment the
order becomes the stall's to act on, which is not always the moment it was
created - once payment is in the picture an order exists for a while before
anybody should be cooking it.
"""

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.device import RiderDevice, VendorDevice
from app.db.models.order import Order
from app.db.session import async_session_factory
from app.modules.notifications.fcm import send_to_token

logger = logging.getLogger(__name__)

# Firebase is not a dependency of taking an order, so it gets a short leash. If
# it has not answered in five seconds the push is lost and the stall sees the
# order on screen instead, which is a far better outcome than holding a worker.
_TIMEOUT = httpx.Timeout(5.0)


def _summary(order: Order) -> tuple[str, str]:
    """The two lines a stall reads on a locked phone."""
    count = sum(item.quantity for item in order.items)
    plural = "item" if count == 1 else "items"
    where = (
        f"Deliver to {order.delivery_location_label}"
        if order.delivery_location_label
        else "Dine in"
    )
    return (
        f"New order - {int(order.total_amount)} rupees",
        f"{count} {plural} - {where}",
    )


async def notify_new_order(order_id, vendor_id, settings: Settings) -> None:
    """Tell every device signed into this stall that an order has arrived.

    Opens its own database session on purpose. This runs after the response has
    been sent, by which point the request's session has been closed by its
    dependency - reusing it would fail with a closed-session error that only
    appears under load.
    """
    if not settings.push_enabled:
        return

    async with async_session_factory() as db:
        from app.modules.orders.service import load_order

        order = await load_order(order_id, db)
        if order is None:
            return

        result = await db.execute(
            select(VendorDevice).where(VendorDevice.vendor_id == vendor_id)
        )
        devices = list(result.scalars().all())
        if not devices:
            return

        title, body = _summary(order)
        data = {
            "type": "new_order",
            "order_id": str(order.id),
            "status": order.status.value,
        }

        await _push(
            devices,
            title=title,
            body=body,
            data=data,
            settings=settings,
            db=db,
            model=VendorDevice,
        )


async def notify_rider_assigned(order_id, rider_id, settings: Settings) -> None:
    """Tell a rider their stall has given them a delivery.

    The rider app polls every twelve seconds, so this is not how they find out -
    it is how they find out while the phone is in their pocket. Same best-effort
    rules as the stall's notification: its own session, failures swallowed, and
    nothing here can fail the assignment that triggered it.
    """
    if not settings.push_enabled:
        return

    async with async_session_factory() as db:
        from app.modules.orders.service import load_order

        order = await load_order(order_id, db)
        if order is None:
            return

        result = await db.execute(select(RiderDevice).where(RiderDevice.rider_id == rider_id))
        devices = list(result.scalars().all())
        if not devices:
            return

        where = order.delivery_location_label or "a campus address"
        count = sum(item.quantity for item in order.items)
        plural = "item" if count == 1 else "items"
        await _push(
            devices,
            title=f"Deliver to {where}",
            # Destination in the title, because that is the one thing that decides
            # whether a rider can take it - an order number means nothing to them.
            body=f"{count} {plural} to collect from the stall",
            data={
                "type": "order_assigned",
                "order_id": str(order.id),
                "status": order.status.value,
            },
            settings=settings,
            db=db,
            model=RiderDevice,
        )


async def _push(devices, *, title, body, data, settings, db, model) -> None:
    """Send one message to every device in a list, and prune the dead ones.

    Shared by the stall's and the rider's notifications because the delivery
    rules are identical: one unreachable phone must not stop the others being
    told, and a token Firebase calls dead is deleted so future sends stop paying
    for a round trip to nowhere.
    """
    dead: list[str] = []
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for device in devices:
            try:
                code = await send_to_token(
                    device.fcm_token,
                    title=title,
                    body=body,
                    data=data,
                    settings=settings,
                    client=client,
                )
            except Exception:
                logger.exception("push to device %s failed", device.id)
                continue
            if code is not None:
                dead.append(device.fcm_token)

    if dead:
        await db.execute(delete(model).where(model.fcm_token.in_(dead)))
        await db.commit()
        logger.info("dropped %d dead push token(s)", len(dead))


async def register_rider_device(
    rider_id, fcm_token: str, platform: str, db: AsyncSession
) -> RiderDevice:
    """Record, or re-record, a rider's phone. Upserts on the token - see
    register_device below for why that matters."""
    now = datetime.now(timezone.utc)
    result = await db.execute(select(RiderDevice).where(RiderDevice.fcm_token == fcm_token))
    device = result.scalar_one_or_none()

    if device is None:
        device = RiderDevice(
            rider_id=rider_id, fcm_token=fcm_token, platform=platform, last_seen_at=now
        )
        db.add(device)
    else:
        device.rider_id = rider_id
        device.platform = platform
        device.last_seen_at = now

    await db.commit()
    await db.refresh(device)
    return device


async def register_device(
    vendor_id, fcm_token: str, platform: str, db: AsyncSession
) -> VendorDevice:
    """Record, or re-record, a phone for this stall.

    Upserts on the token rather than inserting, and moves the token to whoever
    registered it last. Firebase issues a token per app install, so a device
    handed from one stall to another keeps the same one - and without the move,
    that phone would keep buzzing for its old stall's orders.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(select(VendorDevice).where(VendorDevice.fcm_token == fcm_token))
    device = result.scalar_one_or_none()

    if device is None:
        device = VendorDevice(
            vendor_id=vendor_id, fcm_token=fcm_token, platform=platform, last_seen_at=now
        )
        db.add(device)
    else:
        device.vendor_id = vendor_id
        device.platform = platform
        device.last_seen_at = now

    await db.commit()
    await db.refresh(device)
    return device
