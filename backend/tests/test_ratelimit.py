"""Tests for the rate limiter, and especially for who it thinks you are.

A limiter that can be handed a fresh identity per request is not a limiter, so
client_ip gets the most attention here: it is four lines of index arithmetic
standing between the whole module and irrelevance.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.core.limits import MINUTE
from app.core.ratelimit import Limit, client_ip, consume


def settings(**overrides) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        redis_url="redis://localhost:6379/0",
        jwt_secret="test-secret",
        **overrides,
    )


class FakeRequest:
    """Stands in for a Request/WebSocket as far as client_ip cares."""

    def __init__(self, headers=None, peer="10.0.0.1"):
        self.headers = headers or {}

        class _Client:
            host = peer

        self.client = _Client() if peer else None


# --- Identity ---------------------------------------------------------------


def test_uses_peer_address_when_no_proxy_is_trusted():
    request = FakeRequest({"x-forwarded-for": "1.2.3.4"}, peer="10.0.0.1")
    # Nothing in front, so the header is noise and must be ignored entirely.
    assert client_ip(request, settings(trusted_proxy_count=0)) == "10.0.0.1"


def test_reads_the_real_client_through_one_trusted_proxy():
    # What Railway sends when the caller set no header of their own.
    request = FakeRequest({"x-forwarded-for": "203.0.113.9"}, peer="10.0.0.1")
    assert client_ip(request, settings(trusted_proxy_count=1)) == "203.0.113.9"


def test_a_forged_forwarded_for_cannot_change_the_bucket():
    """The attack this function exists to stop.

    A caller who prepends their own X-Forwarded-For gets it *appended to*, not
    replaced - the proxy adds the address it actually saw. Reading from the
    right means we get the proxy's observation and the forged entry is ignored,
    so the attacker keeps hitting the same bucket no matter what they send.
    """
    real = "203.0.113.9"
    for forged in ("1.2.3.4", "9.9.9.9, 8.8.8.8", "not-an-ip"):
        request = FakeRequest({"x-forwarded-for": f"{forged}, {real}"}, peer="10.0.0.1")
        assert client_ip(request, settings(trusted_proxy_count=1)) == real


def test_two_trusted_proxies_look_one_hop_further_left():
    request = FakeRequest(
        {"x-forwarded-for": "1.2.3.4, 203.0.113.9, 10.1.0.7"}, peer="10.0.0.1"
    )
    assert client_ip(request, settings(trusted_proxy_count=2)) == "203.0.113.9"


def test_short_header_does_not_index_off_the_end():
    # Fewer hops present than configured (a direct hit on the app behind the
    # proxy, say). Must degrade, not raise.
    request = FakeRequest({"x-forwarded-for": "203.0.113.9"}, peer="10.0.0.1")
    assert client_ip(request, settings(trusted_proxy_count=3)) == "203.0.113.9"


def test_missing_header_and_missing_peer_still_yields_an_identity():
    assert client_ip(FakeRequest({}, peer=None), settings()) == "unknown"


# --- Counting ---------------------------------------------------------------
#
# These run against a real Redis so the Lua in ratelimit.py is actually
# executed rather than re-implemented in a stub that could agree with a bug.

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


async def test_allows_the_budget_then_refuses(redis):
    identity = f"test:{uuid.uuid4()}"
    budget = Limit(3, MINUTE)

    for _ in range(3):
        await consume(redis, "unit", identity, (budget,))

    with pytest.raises(HTTPException) as exc:
        await consume(redis, "unit", identity, (budget,))
    assert exc.value.status_code == 429
    # Clients need to be told when to come back, not just that they failed.
    assert int(exc.value.headers["Retry-After"]) > 0


async def test_identities_do_not_share_a_bucket(redis):
    budget = Limit(1, MINUTE)
    await consume(redis, "unit", f"a:{uuid.uuid4()}", (budget,))
    # One caller spending their budget must not affect anyone else.
    await consume(redis, "unit", f"b:{uuid.uuid4()}", (budget,))


async def test_names_do_not_share_a_bucket(redis):
    identity = f"test:{uuid.uuid4()}"
    budget = Limit(1, MINUTE)
    await consume(redis, "endpoint-one", identity, (budget,))
    await consume(redis, "endpoint-two", identity, (budget,))


async def test_the_tightest_of_several_windows_wins(redis):
    identity = f"test:{uuid.uuid4()}"
    # Generous per minute, strict per hour: the hour must still bite.
    both = (Limit(100, MINUTE), Limit(2, 3600))
    await consume(redis, "unit", identity, both)
    await consume(redis, "unit", identity, both)
    with pytest.raises(HTTPException) as exc:
        await consume(redis, "unit", identity, both)
    assert exc.value.status_code == 429


# --- Behaviour when Redis is gone -------------------------------------------


class BrokenRedis:
    async def eval(self, *args, **kwargs):
        raise ConnectionError("redis is down")


async def test_fails_open_by_default_so_an_outage_is_not_an_outage():
    # Most endpoints would rather serve traffic unlimited than not at all.
    await consume(BrokenRedis(), "unit", "someone", (Limit(1, MINUTE),))


async def test_fails_closed_where_the_limit_is_the_security_control():
    # The login endpoints pass fail_open=False: silently losing the limiter
    # there is the hole, and they cannot work without Redis anyway.
    with pytest.raises(HTTPException) as exc:
        await consume(
            BrokenRedis(), "unit", "someone", (Limit(1, MINUTE),), fail_open=False
        )
    assert exc.value.status_code == 503


def test_the_limiter_exemption_reads_the_routed_path():
    """The middleware must decide exemption from the same string the router uses.

    request.url is rebuilt by concatenating scheme, host and path and re-parsing
    it, so a path that moves the authority boundary during that re-parse can make
    request.url.path differ from the path actually served (Starlette
    PYSEC-2026-161, -248). Anything deciding who skips a limiter has to read the
    ASGI scope, or an exemption could be granted for a path that is not the one
    being routed.
    """
    from pathlib import Path

    source = Path("app/main.py").read_text()
    body = source.split("async def enforce_request_limits", 1)[1].split("\n@", 1)[0]
    # Comments are stripped first: the explanation of why request.url.path is
    # wrong necessarily names it, and matching that would fail on the fix itself.
    code = "\n".join(
        line.split("#", 1)[0] for line in body.splitlines() if line.strip() != ""
    )
    assert "request.scope" in code
    assert "request.url" not in code
