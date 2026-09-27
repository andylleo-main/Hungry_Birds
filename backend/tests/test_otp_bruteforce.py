"""Guessing a 6-digit code is only hard if guesses are limited."""
import pytest
from fastapi import HTTPException

from app.modules.auth.service import (
    MAX_VERIFY_ATTEMPTS,
    OTP_TTL_SECONDS,
    verify_otp,
)


class FakeRedis:
    """Minimal async stand-in covering the calls verify_otp makes."""

    def __init__(self, initial=None):
        self.store = dict(initial or {})
        self.expiries = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)

    async def incr(self, key):
        self.store[key] = str(int(self.store.get(key, 0)) + 1)
        return int(self.store[key])

    async def expire(self, key, seconds):
        self.expiries[key] = seconds


EMAIL = 'student@bitmesra.ac.in'
CODE_KEY = f'otp:code:{EMAIL}'
FAIL_KEY = f'otp:fail:{EMAIL}'


@pytest.mark.asyncio
async def test_correct_code_succeeds_and_is_consumed():
    redis = FakeRedis({CODE_KEY: '123456'})
    assert await verify_otp(EMAIL, '123456', redis) is True
    # Single use: the code is gone, so replay fails.
    assert await verify_otp(EMAIL, '123456', redis) is False


@pytest.mark.asyncio
async def test_wrong_code_counts_a_failure():
    redis = FakeRedis({CODE_KEY: '123456'})
    assert await verify_otp(EMAIL, '000000', redis) is False
    assert int(redis.store[FAIL_KEY]) == 1
    # The failure counter must expire with the code, not linger forever.
    assert redis.expiries[FAIL_KEY] == OTP_TTL_SECONDS


@pytest.mark.asyncio
async def test_code_is_burned_after_the_attempt_budget():
    redis = FakeRedis({CODE_KEY: '123456'})
    for _ in range(MAX_VERIFY_ATTEMPTS):
        assert await verify_otp(EMAIL, '000000', redis) is False

    # The real code must no longer work - this is what stops the grind.
    assert CODE_KEY not in redis.store

    with pytest.raises(HTTPException) as exc:
        await verify_otp(EMAIL, '123456', redis)
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_further_attempts_stay_locked_out():
    redis = FakeRedis({CODE_KEY: '123456', FAIL_KEY: str(MAX_VERIFY_ATTEMPTS)})
    for _ in range(3):
        with pytest.raises(HTTPException) as exc:
            await verify_otp(EMAIL, '123456', redis)
        assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_a_successful_login_clears_the_failure_budget():
    redis = FakeRedis({CODE_KEY: '123456', FAIL_KEY: '2'})
    assert await verify_otp(EMAIL, '123456', redis) is True
    assert FAIL_KEY not in redis.store
