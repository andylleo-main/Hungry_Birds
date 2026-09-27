"""Tests for the WebSocket ticket, whose whole value is being useless twice."""

import uuid

import pytest

from app.modules.realtime.service import (
    TICKET_TTL_SECONDS,
    acquire_socket_slot,
    issue_ticket,
    redeem_ticket,
    release_socket_slot,
)

redis_asyncio = pytest.importorskip("redis.asyncio")


@pytest.fixture
async def redis():
    client = redis_asyncio.Redis.from_url("redis://localhost:6379/0", decode_responses=True)
    try:
        await client.ping()
    except Exception:
        pytest.skip("needs a local Redis on 6379")
    yield client
    await client.aclose()


async def test_a_ticket_identifies_its_user(redis):
    user_id = uuid.uuid4()
    ticket, ttl = await issue_ticket(user_id, redis)
    assert ttl == TICKET_TTL_SECONDS
    assert await redeem_ticket(ticket, redis) == user_id


async def test_a_ticket_works_exactly_once(redis):
    """The point of the whole design.

    A ticket that leaks into an access log must be worthless to whoever reads
    it, which needs redemption to destroy it - not merely to expire it later.
    """
    ticket, _ = await issue_ticket(uuid.uuid4(), redis)
    assert await redeem_ticket(ticket, redis) is not None
    assert await redeem_ticket(ticket, redis) is None


async def test_a_ticket_is_short_lived(redis):
    ticket, _ = await issue_ticket(uuid.uuid4(), redis)
    ttl = await redis.ttl(f"ws:ticket:{ticket}")
    assert 0 < ttl <= TICKET_TTL_SECONDS


async def test_unknown_and_empty_tickets_are_refused(redis):
    assert await redeem_ticket("", redis) is None
    assert await redeem_ticket("not-a-real-ticket", redis) is None


async def test_a_garbled_stored_value_does_not_crash_the_handshake(redis):
    # Defensive: a non-UUID in the slot must read as "no user", not raise.
    ticket = "deliberately-corrupt"
    await redis.set(f"ws:ticket:{ticket}", "not-a-uuid", ex=30)
    assert await redeem_ticket(ticket, redis) is None


async def test_tickets_are_not_guessable(redis):
    # 32 random bytes, url-safe encoded. Distinctness is the cheap proxy for it.
    seen = set()
    for _ in range(50):
        ticket, _ = await issue_ticket(uuid.uuid4(), redis)
        assert len(ticket) >= 40
        seen.add(ticket)
    assert len(seen) == 50


# --- Concurrent socket slots ------------------------------------------------


async def test_slots_run_out_and_come_back(redis):
    user_id = uuid.uuid4()
    await redis.delete(f"ws:live:{user_id}")

    assert await acquire_socket_slot(user_id, redis, 2) is True
    assert await acquire_socket_slot(user_id, redis, 2) is True
    # Third socket for one account is refused rather than left to pile up.
    assert await acquire_socket_slot(user_id, redis, 2) is False

    await release_socket_slot(user_id, redis)
    assert await acquire_socket_slot(user_id, redis, 2) is True


async def test_a_refused_slot_does_not_leak_a_count(redis):
    """A rejected attempt must not consume anything.

    The check increments first and rolls back on refusal, so getting this wrong
    would mean a user who hits the cap once is locked out for good.
    """
    user_id = uuid.uuid4()
    await redis.delete(f"ws:live:{user_id}")

    assert await acquire_socket_slot(user_id, redis, 1) is True
    for _ in range(5):
        assert await acquire_socket_slot(user_id, redis, 1) is False

    await release_socket_slot(user_id, redis)
    assert await acquire_socket_slot(user_id, redis, 1) is True


async def test_the_counter_expires_so_a_crash_heals_itself(redis):
    # The decrement runs in a finally, which a killed worker never reaches.
    # Without a TTL that would count a user as connected forever.
    user_id = uuid.uuid4()
    await redis.delete(f"ws:live:{user_id}")
    await acquire_socket_slot(user_id, redis, 5)
    assert await redis.ttl(f"ws:live:{user_id}") > 0


async def test_extra_releases_cannot_mint_free_slots(redis):
    user_id = uuid.uuid4()
    await redis.delete(f"ws:live:{user_id}")
    for _ in range(3):
        await release_socket_slot(user_id, redis)
    # Floor is zero, so the cap still applies from a clean slate.
    assert await acquire_socket_slot(user_id, redis, 1) is True
    assert await acquire_socket_slot(user_id, redis, 1) is False
