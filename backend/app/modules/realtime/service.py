"""Short-lived tickets for opening a WebSocket.

A browser cannot set headers on a WebSocket handshake, so whatever authorises
the socket has to travel in the URL - and a URL is the worst place to put a
long-lived credential. It lands in server access logs, proxy logs, browser
history, and any Referer sent from the page. Redaction helps with our own logs
and nothing else.

So the access token never goes in a URL. The client spends it once, over an
ordinary Authorization header, to get a ticket: opaque, random, valid for
thirty seconds, and destroyed the moment it is redeemed. A ticket that leaks
into a log is already useless by the time anyone reads it, and replaying one is
impossible because redemption deletes it.
"""

import secrets
import uuid

from redis.asyncio import Redis

TICKET_TTL_SECONDS = 30

# Redemption has to be atomic: read-then-delete as two calls lets two sockets
# race the same ticket through the gap and both win, which is exactly the
# single-use property we are relying on.
_REDEEM = "local v = redis.call('GET', KEYS[1]); redis.call('DEL', KEYS[1]); return v"


def _ticket_key(ticket: str) -> str:
    return f"ws:ticket:{ticket}"


def _socket_count_key(user_id: uuid.UUID) -> str:
    return f"ws:live:{user_id}"


async def issue_ticket(user_id: uuid.UUID, redis: Redis) -> tuple[str, int]:
    """Mint a single-use ticket for this user. Returns (ticket, ttl_seconds)."""
    ticket = secrets.token_urlsafe(32)
    await redis.set(_ticket_key(ticket), str(user_id), ex=TICKET_TTL_SECONDS)
    return ticket, TICKET_TTL_SECONDS


async def redeem_ticket(ticket: str, redis: Redis) -> uuid.UUID | None:
    """Spend a ticket, returning the user it belonged to. None if it is unknown,
    expired, or already used."""
    if not ticket:
        return None
    raw = await redis.eval(_REDEEM, 1, _ticket_key(ticket))
    if raw is None:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


async def acquire_socket_slot(user_id: uuid.UUID, redis: Redis, maximum: int) -> bool:
    """Take one of this user's concurrent-socket slots, if any are free.

    The counter carries a TTL that is refreshed on every connect. That matters
    because the decrement below runs in a `finally` - which a killed process
    never reaches - and without an expiry a crash would leave a user
    permanently counted as connected. With it, a leaked count clears itself.
    """
    key = _socket_count_key(user_id)
    live = await redis.incr(key)
    await redis.expire(key, 60 * 60)
    if live > maximum:
        await redis.decr(key)
        return False
    return True


async def release_socket_slot(user_id: uuid.UUID, redis: Redis) -> None:
    key = _socket_count_key(user_id)
    if await redis.decr(key) < 0:
        # Never let the counter go negative, or a user accumulates free slots.
        await redis.set(key, 0)
