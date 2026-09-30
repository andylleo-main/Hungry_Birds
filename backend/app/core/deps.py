import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenAudience, TokenType, decode_token
from app.db.models.user import User, UserRole
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)


async def get_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Verify the bearer token and return its claims.

    Split out from get_current_user so the audience check can read the same
    claims without decoding twice - FastAPI caches a dependency's result for the
    life of a request, so both callers share one verification.
    """
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    try:
        return decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")


async def get_current_user(
    payload: dict = Depends(get_token_payload),
    db: AsyncSession = Depends(get_db),
) -> User:
    if payload.get("type") != TokenType.ACCESS.value:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token payload")

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


def require_role(*roles: UserRole):
    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this action")
        return user

    return dependency


def require_audience(*allowed: TokenAudience):
    """Refuse a token minted for a different app.

    A token with no `aud` claim at all is one issued before audiences existed.
    It is answered with 401 rather than 403 on purpose: 401 is what makes the
    web client refresh silently and retry - which mints a token that does carry
    the claim - whereas 403 would surface as a dead end. The cost is that
    anyone signed into the merchant app when this ships signs in once more,
    because a legacy session cannot be assumed to have been a merchant one.
    """

    allowed_values = {a.value for a in allowed}

    async def dependency(payload: dict = Depends(get_token_payload)) -> None:
        audience = payload.get("aud")
        if audience is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in again")
        if audience not in allowed_values:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This account signs in through a different Hungry Birds app",
            )

    return dependency
