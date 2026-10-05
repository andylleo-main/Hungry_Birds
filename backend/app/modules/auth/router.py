import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.config import Settings, get_settings
from app.core.deps import get_current_user, require_audience, require_role
from app.core.ratelimit import limit_by_ip, limit_by_user
from app.core.redis import get_redis
from app.core.security import TokenAudience, create_access_token
from app.db.models.merchant_credential import MerchantCredential
from app.db.models.user import User, UserRole
from app.db.session import get_db
from app.modules.auth.passwords import (
    hash_password_async,
    verify_password,
    verify_password_async,
    waste_time_like_a_verification,
    waste_time_like_a_verification_async,
)
from app.modules.auth.schemas import (
    AccessTokenResponse,
    AdminLogin,
    OTPRequest,
    OTPRequestResponse,
    OTPVerify,
    RefreshRequest,
    SessionOut,
    SetVendorPassword,
    TokenResponse,
    UpdateMe,
    UserOut,
    VendorLogin,
    VendorPasswordState,
)
from app.modules.auth.sessions import (
    SessionRejected,
    create_session,
    list_active,
    revoke_all_for_user,
    revoke_by_id,
    revoke_session,
    rotate_session,
)
from app.modules.auth.service import (
    OTP_RATE_LIMIT_SECONDS,
    assert_allowed_domain,
    normalize_email,
    normalize_phone,
    request_otp,
    verify_otp,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/otp/request",
    response_model=OTPRequestResponse,
    dependencies=[
        Depends(limit_by_ip("otp_request", *limits.OTP_REQUEST_PER_IP, fail_open=False))
    ],
)
async def otp_request(
    payload: OTPRequest,
    background: BackgroundTasks,
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> OTPRequestResponse:
    email = normalize_email(payload.email)
    assert_allowed_domain(email, settings)

    debug_code = await request_otp(email, redis, settings, background)
    return OTPRequestResponse(
        message="OTP sent",
        debug_code=debug_code,
        resend_after_seconds=OTP_RATE_LIMIT_SECONDS,
    )


@router.post(
    "/otp/verify",
    response_model=TokenResponse,
    dependencies=[
        Depends(limit_by_ip("otp_verify", *limits.OTP_VERIFY_PER_IP, fail_open=False))
    ],
)
async def otp_verify(
    payload: OTPVerify,
    request: Request,
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

    _, refresh_token = await create_session(
        user.id,
        db,
        lifetime_days=settings.refresh_token_expire_days,
        user_agent=request.headers.get("user-agent"),
        audience=TokenAudience.WEB.value,
    )

    return TokenResponse(
        access_token=create_access_token(str(user.id), TokenAudience.WEB),
        refresh_token=refresh_token,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/vendor/otp/request",
    response_model=OTPRequestResponse,
    dependencies=[
        Depends(
            limit_by_ip("vendor_otp_request", *limits.VENDOR_OTP_REQUEST_PER_IP, fail_open=False)
        )
    ],
)
async def vendor_otp_request(
    payload: OTPRequest,
    background: BackgroundTasks,
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> OTPRequestResponse:
    """Send a stall owner a sign-in code, at any email address.

    A separate route rather than a flag on the customer one. A flag would need a
    default, and for the web app to keep working the default would have to mean
    "customer" - so the institute-domain rule would sit behind a field that a
    new client, or a refactor, could omit and quietly switch off. Here the
    absence of an audience is not expressible: the customer route checks the
    domain unconditionally, and this route is the only one that does not.

    It also means the two get their own rate limits, which they need: this one
    can be pointed at any inbox on the internet and the other cannot.
    """
    email = normalize_email(payload.email)
    debug_code = await request_otp(email, redis, settings, background)
    return OTPRequestResponse(
        message="OTP sent",
        debug_code=debug_code,
        resend_after_seconds=OTP_RATE_LIMIT_SECONDS,
    )


@router.post(
    "/vendor/otp/verify",
    response_model=TokenResponse,
    dependencies=[
        Depends(
            limit_by_ip("vendor_otp_verify", *limits.VENDOR_OTP_VERIFY_PER_IP, fail_open=False)
        )
    ],
)
async def vendor_otp_verify(
    payload: OTPVerify,
    request: Request,
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Sign a stall owner in, creating the account as a vendor if it is new.

    The role is set here, at INSERT, and nothing changes it afterwards. That is
    the point: an account's role decides whether it can spend money on campus or
    sell food to it, so it should not be a field that a later request can flip.
    Vendor signup used to work by creating an ordinary customer and then
    promoting it, which meant any signed-in student could turn their own account
    into a stall.

    An address that already holds a customer or admin account is refused rather
    than converted. Somebody who is both a student and a stall owner needs two
    addresses; that is a real cost, and it is smaller than a mutable role.
    """
    email = normalize_email(payload.email)

    if not await verify_otp(email, payload.code, redis):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired code")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email, role=UserRole.VENDOR)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif user.role != UserRole.VENDOR:
        # Not an enumeration leak worth worrying about: the caller has already
        # proved they control this mailbox by holding a valid code for it.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This email already has a Hungry Birds account. Use a different address for your stall.",
        )

    _, refresh_token = await create_session(
        user.id,
        db,
        lifetime_days=settings.refresh_token_expire_days,
        user_agent=request.headers.get("user-agent"),
        audience=TokenAudience.MERCHANT.value,
    )

    return TokenResponse(
        access_token=create_access_token(str(user.id), TokenAudience.MERCHANT),
        refresh_token=refresh_token,
        user=UserOut.model_validate(user),
    )


async def _merchant_session(
    user: User, request: Request, db: AsyncSession, settings: Settings
) -> TokenResponse:
    """Issue a merchant session, exactly as the OTP route does.

    Shared so the two ways in cannot drift apart. A password sign-in produces an
    ordinary user_sessions row with a refresh token, not the bare access token
    riders get - merchants already had refresh tokens, so the app's existing
    401-and-retry path keeps working untouched.
    """
    _, refresh_token = await create_session(
        user.id,
        db,
        lifetime_days=settings.refresh_token_expire_days,
        user_agent=request.headers.get("user-agent"),
        audience=TokenAudience.MERCHANT.value,
    )
    return TokenResponse(
        access_token=create_access_token(str(user.id), TokenAudience.MERCHANT),
        refresh_token=refresh_token,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/vendor/login",
    response_model=TokenResponse,
    dependencies=[
        Depends(limit_by_ip("vendor_login", *limits.VENDOR_LOGIN_PER_IP, fail_open=False))
    ],
)
async def vendor_login(
    payload: VendorLogin,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Sign a stall owner in with their email and password.

    Three things must all hold, and failing any of them gives the same answer:
    the account exists, it is a vendor, and it has a password that matches. One
    message for all three, because telling them apart tells somebody which
    addresses are worth attacking - and a stall's address is public on the
    storefront.

    The password alone grants nothing. A customer or admin account is refused
    here even with the right password, the same way the admin route refuses a
    non-admin: a role is not something a login may change.

    There is no way to create a password from this route. The first one is set
    after an email-code sign-in, through the route below - which is also what
    makes "forgot password" need no machinery of its own.
    """
    email = normalize_email(payload.email)

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    credential = None
    if user is not None and user.role is UserRole.VENDOR:
        credential = (
            await db.execute(
                select(MerchantCredential).where(MerchantCredential.user_id == user.id)
            )
        ).scalar_one_or_none()

    if credential is None:
        # No account, not a stall, or no password set. Burn the same work a real
        # verification costs, so a miss is not measurably faster than a wrong
        # password.
        await waste_time_like_a_verification_async()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    if not await verify_password_async(payload.password, credential.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    return await _merchant_session(user, request, db, settings)


@router.get("/vendor/password", response_model=VendorPasswordState)
async def vendor_password_state(
    user: User = Depends(require_role(UserRole.VENDOR)),
    _: None = Depends(require_audience(TokenAudience.MERCHANT)),
    db: AsyncSession = Depends(get_db),
) -> VendorPasswordState:
    """Whether this stall has a password yet, so the app knows whether to ask."""
    exists = (
        await db.execute(
            select(MerchantCredential.id).where(MerchantCredential.user_id == user.id)
        )
    ).scalar_one_or_none()
    return VendorPasswordState(is_set=exists is not None)


@router.put("/vendor/password", response_model=TokenResponse)
async def set_vendor_password(
    payload: SetVendorPassword,
    request: Request,
    user: User = Depends(require_role(UserRole.VENDOR)),
    _: None = Depends(require_audience(TokenAudience.MERCHANT)),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Set or change this stall's password.

    Authenticated, which is what makes "forgot password" need nothing new: the
    way back in is the email code that already exists, and this route is what
    follows it. No reset tokens, no emailed links, nothing extra to expire or
    leak.

    Every other session is revoked and a fresh one is issued and returned. A
    password change has to end the sessions it was meant to end - otherwise
    changing it after losing a phone achieves nothing - and revoking everything
    then handing back a new pair keeps that rule simple, with no "except this
    one" to get wrong.
    """
    password_hash = await hash_password_async(payload.password)

    credential = (
        await db.execute(
            select(MerchantCredential).where(MerchantCredential.user_id == user.id)
        )
    ).scalar_one_or_none()

    if credential is None:
        db.add(MerchantCredential(user_id=user.id, password_hash=password_hash))
    else:
        credential.password_hash = password_hash
    await db.commit()

    await revoke_all_for_user(user.id, db)
    return await _merchant_session(user, request, db, settings)


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    dependencies=[Depends(limit_by_ip("token_refresh", *limits.TOKEN_REFRESH_PER_IP))],
)
async def refresh_token(
    payload: RefreshRequest, db: AsyncSession = Depends(get_db)
) -> AccessTokenResponse:
    """Trade a refresh token for a new access token and a new refresh token.

    The old refresh token stops working here, not when it expires. That is the
    point: it bounds how long a stolen copy is useful, and makes a replay
    detectable - see rotate_session.
    """
    try:
        session, new_refresh = await rotate_session(payload.refresh_token, db)
    except SessionRejected:
        # One message for unknown, expired, revoked and replayed alike. Saying
        # which would tell someone probing with stolen tokens what they have.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in again")

    user = await db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in again")

    # A session stays on the app it was created on. Sessions predating audiences
    # carry none and fall back to the web app, which is the safe direction: it
    # cannot promote an old session into one that reaches vendor endpoints.
    try:
        audience = TokenAudience(session.audience) if session.audience else TokenAudience.WEB
    except ValueError:
        # An unrecognised stored value, e.g. after an audience is renamed. Fall
        # back rather than 500 - refresh is the endpoint that must never be the
        # reason somebody cannot get back in.
        audience = TokenAudience.WEB

    return AccessTokenResponse(
        access_token=create_access_token(str(user.id), audience),
        refresh_token=new_refresh,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/admin/login",
    response_model=TokenResponse,
    dependencies=[
        Depends(limit_by_ip("admin_login", *limits.ADMIN_LOGIN_PER_IP, fail_open=False))
    ],
)
async def admin_login(
    payload: AdminLogin,
    request: Request,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Sign in an admin with a password, skipping the OTP email.

    This exists because the admin is precisely the account you need when email
    is the thing that has broken, and waiting on a code you cannot receive is
    a bad way to be locked out of your own service.

    It is a second door, so it is built like one. It only opens for an account
    that already holds the admin role - the password alone grants nothing.
    It is off unless ADMIN_PASSWORD_HASH is set, it is rate limited hard, and
    the limiter fails closed so that an unreachable Redis cannot turn it into
    an unlimited guessing surface. Everything after this point is the ordinary
    session flow; nothing about it is privileged.
    """
    if not settings.admin_password_hash:
        # Not configured: behave as though the route does not exist rather
        # than advertising a door that is merely locked.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    email = normalize_email(payload.email)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # One message for every failure - unknown address, non-admin account, wrong
    # password. Distinguishing them would let someone map which addresses are
    # admins before they start guessing.
    if user is None or user.role != UserRole.ADMIN:
        # Spend the same time a real check would, so a wrong address is not
        # measurably faster to reject than a wrong password.
        waste_time_like_a_verification()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    if not verify_password(payload.password, settings.admin_password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    _, refresh_token = await create_session(
        user.id,
        db,
        lifetime_days=settings.refresh_token_expire_days,
        user_agent=request.headers.get("user-agent"),
        audience=TokenAudience.WEB.value,
    )
    return TokenResponse(
        access_token=create_access_token(str(user.id), TokenAudience.WEB),
        refresh_token=refresh_token,
        user=UserOut.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> Response:
    """End this device's session.

    Deliberately unauthenticated: signing out must work even when the access
    token has already expired, and the refresh token is itself the proof that
    the caller holds this session. Revoking is idempotent, and an unknown token
    returns the same 204 so this cannot be used to test whether one is valid.
    """
    await revoke_session(payload.refresh_token, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/sessions",
    response_model=list[SessionOut],
    dependencies=[Depends(limit_by_user("profile_read", *limits.PROFILE_READ))],
)
async def my_sessions(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[SessionOut]:
    return [SessionOut.model_validate(s) for s in await list_active(user.id, db)]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_by_user("profile_write", *limits.PROFILE_WRITE))],
)
async def end_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not await revoke_by_id(session_id, user.id, db):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/revoke-all",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_by_user("profile_write", *limits.PROFILE_WRITE))],
)
async def end_all_sessions(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Response:
    """Sign out everywhere - the button you want after losing a phone."""
    await revoke_all_for_user(user.id, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=UserOut,
    dependencies=[Depends(limit_by_user("profile_read", *limits.PROFILE_READ))],
)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.patch(
    "/me",
    response_model=UserOut,
    dependencies=[Depends(limit_by_user("profile_write", *limits.PROFILE_WRITE))],
)
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
