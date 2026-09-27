import secrets

import resend
from fastapi import HTTPException, status
from redis.asyncio import Redis

from app.core.config import Settings

OTP_TTL_SECONDS = 5 * 60
OTP_RATE_LIMIT_SECONDS = 60

# A 6-digit code is only a million possibilities, so the code itself is not
# the defence - limiting guesses is. After this many wrong attempts the code
# is burned and the attacker has to request a new one, which the 60s limit
# plus the hourly cap below make slow enough to be useless.
MAX_VERIFY_ATTEMPTS = 5
# Bounds the "request a fresh code every 60s and keep grinding" loop.
MAX_REQUESTS_PER_HOUR = 10
REQUEST_WINDOW_SECONDS = 60 * 60


def normalize_email(email: str) -> str:
    """Lowercase and strip +tag local-part addressing so name+1@x and name@x
    resolve to the same account (closes an easy multi-account loophole)."""
    local, _, domain = email.strip().lower().partition("@")
    local = local.split("+", 1)[0]
    return f"{local}@{domain}"


def normalize_phone(phone: str) -> str:
    """Normalize an Indian mobile number to E.164 (+919876543210).

    Accepts what people actually type: spaces, dashes, a leading 0, a +91 or 91
    country prefix. Rejects anything that isn't a valid Indian mobile, which
    start with 6-9. Raises HTTPException so callers can pass user input
    straight through.
    """
    digits = "".join(ch for ch in phone if ch.isdigit())

    # Strip the country code or a domestic trunk '0' to get the 10-digit number.
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10 or digits[0] not in "6789":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Enter a valid 10-digit Indian mobile number.",
        )
    return f"+91{digits}"


def assert_allowed_domain(email: str, settings: Settings) -> None:
    domain = email.rsplit("@", 1)[-1].lower()
    if domain != settings.allowed_email_domain.lower():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Only @{settings.allowed_email_domain} email addresses may sign up.",
        )


def _otp_key(email: str) -> str:
    return f"otp:code:{email}"


def _rate_limit_key(email: str) -> str:
    return f"otp:rl:{email}"


def _attempt_key(email: str) -> str:
    return f"otp:fail:{email}"


def _hourly_key(email: str) -> str:
    return f"otp:hr:{email}"


async def request_otp(email: str, redis: Redis, settings: Settings) -> str | None:
    """Generates and stores an OTP, sends it via Resend. Returns the code
    only when OTP_DEBUG_ECHO is enabled, for local-dev convenience."""
    if await redis.get(_rate_limit_key(email)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Please wait a minute before requesting another code.",
        )

    # Without an hourly cap, an attacker can mint a fresh code every 60s and
    # keep guessing indefinitely, which defeats the per-code attempt limit.
    hourly = await redis.incr(_hourly_key(email))
    if hourly == 1:
        await redis.expire(_hourly_key(email), REQUEST_WINDOW_SECONDS)
    if hourly > MAX_REQUESTS_PER_HOUR:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many codes requested for this address. Try again later.",
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    await redis.set(_otp_key(email), code, ex=OTP_TTL_SECONDS)
    await redis.set(_rate_limit_key(email), "1", ex=OTP_RATE_LIMIT_SECONDS)
    # A new code starts a fresh attempt budget.
    await redis.delete(_attempt_key(email))

    if settings.resend_api_key:
        resend.api_key = settings.resend_api_key
        resend.Emails.send(
            {
                "from": settings.resend_from_email,
                "to": [email],
                "subject": "Your Hunger Birds login code",
                "html": (
                    f"<p>Your Hunger Birds login code is:</p>"
                    f"<h2>{code}</h2>"
                    f"<p>It expires in 5 minutes. If you didn't request this, ignore this email.</p>"
                ),
            }
        )

    return code if settings.debug_echo_enabled else None


async def verify_otp(email: str, code: str, redis: Redis) -> bool:
    """Checks a code, counting wrong guesses and burning the code once too
    many pile up.

    Returns False for an ordinary bad/expired code. Raises 429 once the
    attempt budget is spent, so the caller can tell the user to request a new
    one rather than letting them keep grinding.
    """
    attempts = int(await redis.get(_attempt_key(email)) or 0)
    if attempts >= MAX_VERIFY_ATTEMPTS:
        await redis.delete(_otp_key(email))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many incorrect codes. Request a new one.",
        )

    stored = await redis.get(_otp_key(email))
    if stored is None or not secrets.compare_digest(stored, code):
        # Counter lives as long as the code, so a fresh code resets the budget.
        failures = await redis.incr(_attempt_key(email))
        if failures == 1:
            await redis.expire(_attempt_key(email), OTP_TTL_SECONDS)
        if failures >= MAX_VERIFY_ATTEMPTS:
            await redis.delete(_otp_key(email))
        return False

    await redis.delete(_otp_key(email))
    await redis.delete(_attempt_key(email))
    return True
