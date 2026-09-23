import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.deps import get_current_user
from app.core.redis import get_redis
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.db.models.user import User
from app.db.session import get_db
from app.modules.auth.schemas import (
    AccessTokenResponse,
    OTPRequest,
    OTPRequestResponse,
    OTPVerify,
    RefreshRequest,
    TokenResponse,
    UpdateMe,
    UserOut,
)
from app.modules.auth.service import (
    assert_allowed_domain,
    normalize_email,
    normalize_phone,
    request_otp,
    verify_otp,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/otp/request", response_model=OTPRequestResponse)
async def otp_request(
    payload: OTPRequest,
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> OTPRequestResponse:
    email = normalize_email(payload.email)
    assert_allowed_domain(email, settings)

    debug_code = await request_otp(email, redis, settings)
    return OTPRequestResponse(message="OTP sent", debug_code=debug_code)


@router.post("/otp/verify", response_model=TokenResponse)
async def otp_verify(
    payload: OTPVerify,
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    email = normalize_email(payload.email)
    assert_allowed_domain(email, settings)

    if not await verify_otp(email, payload.code, redis):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired code")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
        user=UserOut.model_validate(user),
    )


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh_token(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> AccessTokenResponse:
    try:
        decoded = decode_token(payload.refresh_token)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")

    if decoded.get("type") != TokenType.REFRESH.value:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")

    user_id = uuid.UUID(decoded["sub"])
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    return AccessTokenResponse(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: UpdateMe,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    changes = payload.model_dump(exclude_unset=True)

    if "phone" in changes and changes["phone"] is not None:
        changes["phone"] = normalize_phone(changes["phone"])
    if "full_name" in changes and changes["full_name"] is not None:
        changes["full_name"] = changes["full_name"].strip() or None

    for field, value in changes.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)
