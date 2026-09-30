from datetime import datetime, timedelta, timezone
from enum import StrEnum

import jwt

from app.core.config import get_settings


class TokenType(StrEnum):
    """Access tokens are JWTs; refresh tokens are not.

    Refresh tokens moved to opaque, database-backed session keys so they can be
    revoked (see modules/auth/sessions.py). REFRESH stays here so that any JWT
    still carrying it - issued before that change, or forged - fails the
    "is this an access token" check in deps.get_current_user rather than being
    treated as one.
    """

    ACCESS = "access"
    REFRESH = "refresh"


class TokenAudience(StrEnum):
    """Which app a token was minted for.

    Three clients now sign in against one API, and each has a different rule
    about who may hold an account: the web app is institute-email customers, the
    merchant app is vendors on any address, the rider app is id-and-password
    couriers. Without this, a token from any one of them worked everywhere,
    which meant the rules only really applied at the moment of login.

    It is defence in depth, not a wall. Nothing stops someone calling the
    merchant login route with curl - the API is public and there is no client
    attestation. What it does buy is that a session belonging to one app cannot
    be replayed against another's endpoints.
    """

    WEB = "web"
    MERCHANT = "merchant"
    RIDER = "rider"


def _create_token(
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    audience: TokenAudience,
    extra: dict | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type.value,
        "aud": audience.value,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    user_id: str,
    audience: TokenAudience = TokenAudience.WEB,
    extra: dict | None = None,
) -> str:
    settings = get_settings()
    return _create_token(
        user_id,
        TokenType.ACCESS,
        timedelta(minutes=settings.access_token_expire_minutes),
        audience,
        extra,
    )


def decode_token(token: str) -> dict:
    """Verify a token's signature and expiry, and hand back its claims.

    `verify_aud` is off deliberately, and it is not a weakening. PyJWT's own
    audience check needs the expected value at decode time, but this function is
    the single chokepoint every endpoint decodes through and the audience a
    given endpoint requires differs per endpoint - so there is no one value to
    pass here. Worse, PyJWT raises InvalidAudienceError when a token carries
    `aud` and the caller names none, which would make every token this module
    now mints undecodable. The claim is therefore read out and enforced by
    deps.require_audience, where the per-endpoint policy actually lives.
    """
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"verify_aud": False},
    )
