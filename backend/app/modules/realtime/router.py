import asyncio
import contextlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.config import Settings, get_settings
from app.core.deps import get_current_user
from app.core.ratelimit import client_ip, consume, limit_by_user
from app.core.redis import get_redis
from app.db.models.order import Order
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.orders.service import may_view_order, order_channel, vendor_channel
from app.modules.realtime.service import (
    acquire_socket_slot,
    issue_ticket,
    redeem_ticket,
    release_socket_slot,
)

router = APIRouter(tags=["realtime"])

CLOSE_UNAUTHORIZED = 4401
CLOSE_RATE_LIMITED = 4429


class WSTicket(BaseModel):
    ticket: str
    expires_in: int


@router.post(
    "/realtime/ticket",
    response_model=WSTicket,
    dependencies=[Depends(limit_by_user("ws_ticket", *limits.WS_TICKET))],
)
async def create_ws_ticket(
    user: User = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
) -> WSTicket:
    """Exchange an access token for a single-use ticket to open a socket with.

    The token stays in an Authorization header where it belongs; only the
    throwaway ticket ever appears in a URL. See realtime/service.py.
    """
    ticket, ttl = await issue_ticket(user.id, redis)
    return WSTicket(ticket=ticket, expires_in=ttl)


async def _authenticate_ws(ticket: str, db: AsyncSession, redis: Redis) -> User | None:
    user_id = await redeem_ticket(ticket, redis)
    if user_id is None:
        return None
    return await db.get(User, user_id)


async def _pump_channel_to_socket(websocket: WebSocket, redis: Redis, channel: str) -> None:
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()


async def _watch_for_disconnect(websocket: WebSocket) -> None:
    # Clients don't need to send anything over this socket; this loop's only
    # job is to notice (via WebSocketDisconnect) when they go away.
    while True:
        await websocket.receive_text()


async def _guard_handshake(websocket: WebSocket, redis: Redis, settings: Settings) -> bool:
    """Cap handshakes per address before any work is done.

    Sending handshakes is cheap; serving one costs us a Redis pub/sub
    subscription, so an unlimited reconnect loop is a way to exhaust
    connections with a single client.
    """
    address = client_ip(websocket, settings)
    try:
        await consume(
            redis,
            "ws_connect",
            f"ip:{address}",
            limits.WS_CONNECT_PER_IP,
        )
    except HTTPException:
        # close() before accept() rejects the handshake outright, which is all a
        # flooding client deserves.
        await websocket.close(code=CLOSE_RATE_LIMITED)
        return False
    return True


@router.websocket("/ws/orders/{order_id}")
async def ws_order_tracking(
    websocket: WebSocket,
    order_id: uuid.UUID,
    ticket: str = Query(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> None:
    if not await _guard_handshake(websocket, redis, settings):
        return

    await websocket.accept()

    user = await _authenticate_ws(ticket, db, redis)
    order = await db.get(Order, order_id) if user is not None else None

    # The same predicate the HTTP route uses. This branch used to be a second
    # copy that had drifted: it let a stall subscribe to an order of theirs that
    # nobody had paid for, which GET /orders/{id} refuses.
    authorized = (
        order is not None
        and user is not None
        and await may_view_order(order, user, db)
    )

    if not authorized:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    await _run_socket_after_accept(websocket, redis, order_channel(order_id), user)


@router.websocket("/ws/vendor/{vendor_id}")
async def ws_vendor_queue(
    websocket: WebSocket,
    vendor_id: uuid.UUID,
    ticket: str = Query(...),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> None:
    if not await _guard_handshake(websocket, redis, settings):
        return

    await websocket.accept()

    user = await _authenticate_ws(ticket, db, redis)
    vendor = await db.get(Vendor, vendor_id) if user is not None else None

    authorized = (
        vendor is not None
        and user is not None
        and ((user.role == UserRole.VENDOR and vendor.user_id == user.id) or user.role == UserRole.ADMIN)
    )

    if not authorized:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return

    await _run_socket_after_accept(websocket, redis, vendor_channel(vendor_id), user)


async def _run_socket_after_accept(
    websocket: WebSocket, redis: Redis, channel: str, user: User
) -> None:
    if not await acquire_socket_slot(user.id, redis, limits.MAX_SOCKETS_PER_USER):
        await websocket.close(code=CLOSE_RATE_LIMITED)
        return

    pump_task = asyncio.create_task(_pump_channel_to_socket(websocket, redis, channel))
    watch_task = asyncio.create_task(_watch_for_disconnect(websocket))
    try:
        await asyncio.wait([pump_task, watch_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        pump_task.cancel()
        watch_task.cancel()
        for task in (pump_task, watch_task):
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, Exception):
                await task
        with contextlib.suppress(Exception):
            await release_socket_slot(user.id, redis)
