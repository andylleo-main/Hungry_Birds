import secrets

import resend
from fastapi import HTTPException, status
from redis.asyncio import Redis

from app.core.config import Settings

OTP_TTL_SECONDS = 5 * 60
OTP_RATE_LIMIT_SECONDS = 60


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


async def request_otp(email: str, redis: Redis, settings: Settings) -> str | None:
    """Generates and stores an OTP, sends it via Resend. Returns the code
    only when OTP_DEBUG_ECHO is enabled, for local-dev convenience."""
    if await redis.get(_rate_limit_key(email)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Please wait a minute before requesting another code.",
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    await redis.set(_otp_key(email), code, ex=OTP_TTL_SECONDS)
    await redis.set(_rate_limit_key(email), "1", ex=OTP_RATE_LIMIT_SECONDS)

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

    return code if settings.otp_debug_echo else None


async def verify_otp(email: str, code: str, redis: Redis) -> bool:
    stored = await redis.get(_otp_key(email))
    if stored is None or stored != code:
        return False
    await redis.delete(_otp_key(email))
    return True
