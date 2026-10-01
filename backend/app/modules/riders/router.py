import uuid

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.deps import get_current_rider
from app.core.ratelimit import limit_by_ip, limit_by_user
from app.core.redis import get_redis
from app.core.security import create_rider_access_token
from app.db.models.order import Order
from app.db.models.rider import Rider
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.auth.passwords import waste_time_like_a_verification
from app.modules.auth.service import normalize_phone
from app.modules.orders.schemas import OrderOut, OrderStatusUpdate
from app.modules.orders.service import (
    RIDER_ALLOWED_TARGETS,
    assert_transition,
    load_order,
    order_query,
    publish_order_event,
)
from app.modules.riders.credentials import (
    generate_password,
    hash_password_async,
    suggest_login_id,
    verify_password_async,
)
from app.modules.riders.schemas import (
    RiderCreate,
    RiderCredentials,
    RiderLogin,
    RiderOut,
    RiderTokenResponse,
    RiderUpdate,
)
from app.modules.vendors.deps import get_own_vendor

# The merchant's own riders. Riders are the stall's staff, not the platform's, so
# this sits in the vendor namespace beside menu and orders - there is
# deliberately no admin route for creating one.
router = APIRouter(prefix="/vendors/me/riders", tags=["riders"])

# Where the rider app signs in.
auth_router = APIRouter(prefix="/auth/rider", tags=["riders"])

# What the rider app uses once signed in.
rider_router = APIRouter(prefix="/rider", tags=["riders"])

# How many times to retry a generated login id before giving up. Ids carry four
# random digits, so a collision needs the same stem twice; three tries is
# already generous.
_LOGIN_ID_ATTEMPTS = 3


async def _own_rider(rider_id: uuid.UUID, vendor: Vendor, db: AsyncSession) -> Rider:
    """One of this stall's riders, or 404.

    Filtered on both the id and the stall, never a bare db.get, so another
    stall's rider is indistinguishable from one that does not exist - the same
    shape the menu routes use.
    """
    result = await db.execute(
        select(Rider).where(Rider.id == rider_id, Rider.vendor_id == vendor.id)
    )
    rider = result.scalar_one_or_none()
    if rider is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rider not found")
    return rider


@router.post(
    "",
    response_model=RiderCredentials,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_user("rider_write", *limits.RIDER_WRITE))],
)
async def create_rider(
    payload: RiderCreate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> RiderCredentials:
    """Add a rider, and hand back the one copy of their password.

    The password is generated here, hashed, and returned in this response only.
    It is never stored in readable form, so this response and the Regenerate
    route are the only places it ever exists - which is also why the merchant can
    always produce a working password without one sitting in the database waiting
    for a backup to leak.
    """
    phone = normalize_phone(payload.phone)
    password = generate_password()
    password_hash = await hash_password_async(password)

    # Read everything off the ORM objects BEFORE the retry loop.
    #
    # db.rollback() expires every object in the session, so a second pass that
    # touched `vendor.id` would make SQLAlchemy reload it - and attribute access
    # is synchronous, which in an async session raises MissingGreenlet rather
    # than quietly going to the database. The effect was that a login-id
    # collision returned 500 instead of doing the retry this loop exists for.
    vendor_id = vendor.id

    # Retry on a collision rather than pre-checking: a SELECT then an INSERT is a
    # race, and the unique index is the real arbiter.
    last_error: IntegrityError | None = None
    for _ in range(_LOGIN_ID_ATTEMPTS):
        login_id = payload.login_id or suggest_login_id(payload.display_name)
        rider = Rider(
            vendor_id=vendor_id,
            login_id=login_id,
            display_name=payload.display_name,
            phone=phone,
            password_hash=password_hash,
        )
        db.add(rider)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            last_error = exc
            if payload.login_id is not None:
                # They chose it, so tell them rather than silently picking
                # another and leaving them wondering what their rider's id is.
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"The login id '{payload.login_id}' is already taken. Try another.",
                )
            continue
        await db.refresh(rider)
        return RiderCredentials(**RiderOut.model_validate(rider).model_dump(), password=password)

    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, "Could not allocate a login id. Try again."
    ) from last_error


@router.get(
    "",
    response_model=list[RiderOut],
    dependencies=[Depends(limit_by_user("rider_read", *limits.RIDER_READ))],
)
async def list_riders(
    vendor: Vendor = Depends(get_own_vendor), db: AsyncSession = Depends(get_db)
) -> list[RiderOut]:
    result = await db.execute(
        select(Rider).where(Rider.vendor_id == vendor.id).order_by(Rider.created_at)
    )
    return [RiderOut.model_validate(r) for r in result.scalars().all()]


@router.patch(
    "/{rider_id}",
    response_model=RiderOut,
    dependencies=[Depends(limit_by_user("rider_write", *limits.RIDER_WRITE))],
)
async def update_rider(
    rider_id: uuid.UUID,
    payload: RiderUpdate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> RiderOut:
    rider = await _own_rider(rider_id, vendor, db)
    changes = payload.model_dump(exclude_unset=True)

    # Assigned by name, not in a loop over the payload. The same reasoning as the
    # stall profile: a loop would make every field added to RiderUpdate writable
    # without anything in the diff looking like an authorization change, and
    # password_hash and credential_version live on this model.
    if "display_name" in changes and changes["display_name"] is not None:
        rider.display_name = changes["display_name"]
    if "phone" in changes and changes["phone"] is not None:
        rider.phone = normalize_phone(changes["phone"])
    if "is_active" in changes and changes["is_active"] is not None:
        rider.is_active = changes["is_active"]
        if not rider.is_active:
            # Switching a rider off must end their session now, not whenever
            # their token happens to expire. get_current_rider checks both.
            rider.credential_version += 1

    await db.commit()
    await db.refresh(rider)
    return RiderOut.model_validate(rider)


@router.post(
    "/{rider_id}/password",
    response_model=RiderCredentials,
    dependencies=[Depends(limit_by_user("rider_write", *limits.RIDER_WRITE))],
)
async def regenerate_password(
    rider_id: uuid.UUID,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> RiderCredentials:
    """Issue a new password and show it once.

    This is what makes storing only a hash workable: a merchant who has forgotten
    a rider's password does not need to recover it, they replace it. Bumping the
    credential version in the same transaction means the rider's old device is
    signed out at the same moment - otherwise a rider who had left would keep a
    working token and this button would do nothing that mattered.
    """
    rider = await _own_rider(rider_id, vendor, db)
    password = generate_password()
    rider.password_hash = await hash_password_async(password)
    rider.credential_version += 1
    await db.commit()
    await db.refresh(rider)
    return RiderCredentials(**RiderOut.model_validate(rider).model_dump(), password=password)


@auth_router.post(
    "/login",
    response_model=RiderTokenResponse,
    dependencies=[
        Depends(limit_by_ip("rider_login", *limits.RIDER_LOGIN_PER_IP, fail_open=False))
    ],
)
async def rider_login(
    payload: RiderLogin,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RiderTokenResponse:
    """Sign a rider in with the id and password their stall gave them.

    Built like the admin door it is modelled on: one message for an unknown id, an
    inactive rider and a wrong password alike, the same work spent on a miss as on
    a real check so a wrong id is not measurably faster to reject, and a limiter
    that fails closed - an unreachable Redis must not turn a 34-bit password into
    an unlimited guessing surface.
    """
    result = await db.execute(select(Rider).where(Rider.login_id == payload.login_id))
    rider = result.scalar_one_or_none()

    if rider is None or not rider.is_active:
        await _waste_time()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong login id or password")

    if not await verify_password_async(payload.password, rider.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong login id or password")

    vendor = await db.get(Vendor, rider.vendor_id)
    return RiderTokenResponse(
        access_token=create_rider_access_token(str(rider.id), rider.credential_version),
        rider=RiderOut.model_validate(rider),
        stall_name=vendor.stall_name if vendor else "Your stall",
    )


async def _waste_time() -> None:
    """Spend a real check's worth of work on a miss, off the event loop."""
    await anyio.to_thread.run_sync(waste_time_like_a_verification)


@rider_router.get(
    "/me",
    response_model=RiderOut,
    dependencies=[Depends(limit_by_ip("rider_read", *limits.RIDER_READ))],
)
async def rider_me(rider: Rider = Depends(get_current_rider)) -> RiderOut:
    return RiderOut.model_validate(rider)


@rider_router.get(
    "/orders",
    response_model=list[OrderOut],
    dependencies=[Depends(limit_by_ip("rider_orders", *limits.RIDER_ORDERS_READ))],
)
async def rider_orders(
    rider: Rider = Depends(get_current_rider),
    db: AsyncSession = Depends(get_db),
) -> list[OrderOut]:
    """Every order assigned to the signed-in rider, newest first.

    Carries the customer's name and number, which is the point of assignment: a
    rider standing outside a hostel needs to be able to ring the person. It
    reaches this rider only for orders this stall has actually given them.

    Polled by the rider app rather than pushed over a socket. A rider holds one
    or two orders at a time, so a short poll of one small query costs less than
    giving a third audience its own ticket-and-socket path - and it cannot get
    wedged in a way that silently stops delivering updates.
    """
    result = await db.execute(
        order_query(Order.rider_id == rider.id).order_by(Order.created_at.desc())
    )
    return [OrderOut.model_validate(o) for o in result.scalars().all()]


@rider_router.patch(
    "/orders/{order_id}/status",
    response_model=OrderOut,
    dependencies=[Depends(limit_by_ip("rider_write", *limits.RIDER_WRITE))],
)
async def rider_update_status(
    order_id: uuid.UUID,
    payload: OrderStatusUpdate,
    rider: Rider = Depends(get_current_rider),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> OrderOut:
    """A rider marks an order picked up, or delivered.

    Narrower than the stall's equivalent: a rider may only move an order to the
    two statuses that describe their own leg of it. Everything else - accepting,
    rejecting, cooking - stays the stall's to say, which is why the allowed set
    is a named constant rather than the same transition table the merchant uses.
    """
    result = await db.execute(
        order_query(Order.id == order_id, Order.rider_id == rider.id)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    if payload.status not in RIDER_ALLOWED_TARGETS:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "A rider can only mark an order picked up or delivered",
        )
    assert_transition(order, payload.status)

    order.status = payload.status
    await db.commit()

    order = await load_order(order.id, db)
    await publish_order_event(redis, order)
    return OrderOut.model_validate(order)
