"""The admin's coupon desk: make them, edit them, and see where they went.

Gated on the router rather than per handler, like admin/menu_router.py, so a
route added later is admin-only by default instead of by remembering.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import limits
from app.core.deps import require_role
from app.core.ratelimit import limit_by_user
from app.db.models.coupon import (
    Coupon,
    CouponAudience,
    CouponAudienceMember,
    CouponRedemption,
    ExpiryType,
    RedemptionState,
)
from app.db.models.order import Order
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.coupons import service
from app.modules.coupons.schemas import AdminCouponIn, AdminCouponOut, RedemptionOut

router = APIRouter(
    prefix="/admin/coupons",
    tags=["admin"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)


async def _as_out(coupon: Coupon, stall_name: str | None, db: AsyncSession) -> AdminCouponOut:
    return AdminCouponOut(
        id=coupon.id,
        code=coupon.code,
        vendor_id=coupon.vendor_id,
        stall_name=stall_name,
        discount_type=coupon.discount_type,
        discount_value=coupon.discount_value,
        max_discount=coupon.max_discount,
        expiry_type=coupon.expiry_type,
        max_uses=coupon.max_uses,
        expires_at=coupon.expires_at,
        min_order_value=coupon.min_order_value,
        audience=coupon.audience,
        audience_emails=sorted(m.email for m in coupon.audience_members),
        description=coupon.description,
        is_active=coupon.is_active,
        one_per_customer=coupon.one_per_customer,
        show_in_offers=coupon.show_in_offers,
        created_at=coupon.created_at,
        uses=await service.live_uses(coupon.id, db),
    )


async def _load(coupon_id: uuid.UUID, db: AsyncSession) -> Coupon:
    coupon = (
        await db.execute(
            select(Coupon)
            .where(Coupon.id == coupon_id)
            .options(selectinload(Coupon.audience_members))
        )
    ).scalar_one_or_none()
    if coupon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Coupon not found")
    return coupon


async def _stall_names(db: AsyncSession) -> dict[uuid.UUID, str]:
    rows = await db.execute(select(Vendor.id, Vendor.stall_name))
    return {row.id: row.stall_name for row in rows}


async def _write_audience(coupon: Coupon, payload: AdminCouponIn, db: AsyncSession) -> None:
    """Replace the allowed addresses.

    A full replacement rather than a diff, so the admin's form is the whole
    truth - the same reason the stall's delivery locations are written that way.
    Cleared outright when the audience is not NAMED, so a list left behind by an
    earlier edit cannot quietly come back into force if somebody switches the
    audience again.
    """
    await db.execute(
        delete(CouponAudienceMember).where(CouponAudienceMember.coupon_id == coupon.id)
    )
    if payload.audience is not CouponAudience.NAMED:
        return
    for email in {str(e).strip().lower() for e in payload.audience_emails}:
        db.add(CouponAudienceMember(coupon_id=coupon.id, email=email))


def _apply(coupon: Coupon, payload: AdminCouponIn) -> None:
    coupon.code = service.normalise(payload.code)
    coupon.vendor_id = payload.vendor_id
    coupon.discount_type = payload.discount_type
    coupon.discount_value = payload.discount_value
    # Only meaningful on a percentage. Cleared on a flat coupon rather than
    # ignored, so the row never carries a number that reads as a rule it is not.
    coupon.max_discount = (
        payload.max_discount if payload.discount_type.value == "percent" else None
    )
    coupon.expiry_type = payload.expiry_type
    # Likewise: the unused half of the expiry pair is cleared, so a coupon
    # switched from a date to a count does not keep a date that nothing reads.
    coupon.max_uses = payload.max_uses if payload.expiry_type is ExpiryType.COUNT else None
    coupon.expires_at = payload.expires_at if payload.expiry_type is ExpiryType.DATE else None
    coupon.min_order_value = payload.min_order_value
    coupon.audience = payload.audience
    coupon.description = payload.description
    coupon.is_active = payload.is_active
    coupon.one_per_customer = payload.one_per_customer
    coupon.show_in_offers = payload.show_in_offers


@router.get(
    "",
    response_model=list[AdminCouponOut],
    dependencies=[Depends(limit_by_user("admin_read", *limits.ADMIN_READ))],
)
async def list_coupons(db: AsyncSession = Depends(get_db)) -> list[AdminCouponOut]:
    """Every coupon, newest first, each with its uses counted from its rows."""
    coupons = (
        await db.execute(
            select(Coupon)
            .options(selectinload(Coupon.audience_members))
            .order_by(Coupon.created_at.desc())
        )
    ).scalars().all()
    names = await _stall_names(db)
    return [await _as_out(c, names.get(c.vendor_id), db) for c in coupons]


@router.post(
    "",
    response_model=AdminCouponOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_user("admin_write", *limits.ADMIN_WRITE))],
)
async def create_coupon(
    payload: AdminCouponIn, db: AsyncSession = Depends(get_db)
) -> AdminCouponOut:
    now = datetime.now(timezone.utc)
    coupon = Coupon(created_at=now, updated_at=now)
    _apply(coupon, payload)
    db.add(coupon)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        # The unique index on `code` fired. Said plainly, because the admin's
        # next move is to pick another word rather than to read a stack trace.
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A coupon with the code {service.normalise(payload.code)} already exists"
        )
    await _write_audience(coupon, payload, db)
    await db.commit()
    coupon = await _load(coupon.id, db)
    names = await _stall_names(db)
    return await _as_out(coupon, names.get(coupon.vendor_id), db)


@router.put(
    "/{coupon_id}",
    response_model=AdminCouponOut,
    dependencies=[Depends(limit_by_user("admin_write", *limits.ADMIN_WRITE))],
)
async def update_coupon(
    coupon_id: uuid.UUID, payload: AdminCouponIn, db: AsyncSession = Depends(get_db)
) -> AdminCouponOut:
    """Edit a coupon in place, keeping every use it has already seen.

    Editing does not touch the redemptions: what a student was given does not
    change because the poster did. That is why `coupon_redemptions.discount`
    stores the figure rather than recomputing it.
    """
    coupon = await _load(coupon_id, db)
    _apply(coupon, payload)
    coupon.updated_at = datetime.now(timezone.utc)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Another coupon already has that code"
        )
    await _write_audience(coupon, payload, db)
    await db.commit()
    coupon = await _load(coupon.id, db)
    names = await _stall_names(db)
    return await _as_out(coupon, names.get(coupon.vendor_id), db)


@router.delete(
    "/{coupon_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_by_user("admin_write", *limits.ADMIN_WRITE))],
)
async def delete_coupon(coupon_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    """Remove a coupon outright, and its redemption history with it.

    A coupon somebody has used is usually better switched off than deleted - the
    log is the only record of what was given away - so the response says so when
    there is history to lose. It still deletes: an admin who asked twice means
    it, and refusing would leave no way to clear a code made by mistake.
    """
    coupon = await _load(coupon_id, db)
    await db.delete(coupon)
    await db.commit()


@router.get(
    "/redemptions",
    response_model=list[RedemptionOut],
    dependencies=[Depends(limit_by_user("admin_read", *limits.ADMIN_READ))],
)
async def list_redemptions(
    limit: int = Query(100, ge=1, le=500), db: AsyncSession = Depends(get_db)
) -> list[RedemptionOut]:
    """Who used what, on which order, and where that use got to.

    Newest first - the question an admin has is almost always about something
    that just happened.
    """
    rows = await db.execute(
        select(CouponRedemption, Coupon.code, User.email, Order.order_number)
        .join(Coupon, Coupon.id == CouponRedemption.coupon_id)
        .join(User, User.id == CouponRedemption.user_id)
        .outerjoin(Order, Order.id == CouponRedemption.order_id)
        .order_by(CouponRedemption.created_at.desc())
        .limit(limit)
    )
    return [
        RedemptionOut(
            id=r.id,
            code=code,
            customer_email=email,
            order_id=r.order_id,
            order_number=order_number,
            discount=r.discount,
            state=r.state,
            created_at=r.created_at,
            settled_at=r.settled_at,
        )
        for r, code, email, order_number in rows
    ]


@router.post(
    "/redemptions/{redemption_id}/hand-back",
    response_model=RedemptionOut,
    dependencies=[Depends(limit_by_user("admin_write", *limits.ADMIN_WRITE))],
)
async def hand_back_redemption(
    redemption_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> RedemptionOut:
    """Give a use back by hand.

    The same thing a refused order does automatically, through the same function,
    so the manual path and the automatic one cannot drift apart. For the cases
    the automatic one cannot know about: a student who was charged for an order
    that went wrong in some way the status machine does not model.

    Idempotent. Pressing it twice returns one use, not two.
    """
    row = await db.get(CouponRedemption, redemption_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Redemption not found")
    if row.state is RedemptionState.RETURNED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That use has already been handed back"
        )

    if row.order_id is not None:
        await service.hand_back(row.order_id, db)
    else:
        # A redemption whose order was deleted. hand_back finds rows by order,
        # so this one has to be settled directly - and it is still worth handing
        # back, because the use it holds is otherwise locked up forever.
        row.state = RedemptionState.RETURNED
        row.settled_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)

    code = await db.scalar(select(Coupon.code).where(Coupon.id == row.coupon_id))
    email = await db.scalar(select(User.email).where(User.id == row.user_id))
    number = (
        await db.scalar(select(Order.order_number).where(Order.id == row.order_id))
        if row.order_id
        else None
    )
    return RedemptionOut(
        id=row.id,
        code=code or "",
        customer_email=email or "",
        order_id=row.order_id,
        order_number=number,
        discount=row.discount,
        state=row.state,
        created_at=row.created_at,
        settled_at=row.settled_at,
    )


@router.post(
    "/cleanup-expired",
    dependencies=[Depends(limit_by_user("admin_write", *limits.ADMIN_WRITE))],
)
async def cleanup_expired(db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """Delete dated coupons whose date has passed.

    Dated ones only. A count-based coupon that has been fully claimed is not
    expired in the same sense - it may be worth raising the limit on, and its
    log is the record of a promotion that worked.

    Returns how many went, so the button can say so rather than leaving an admin
    to count rows.
    """
    now = datetime.now(timezone.utc)
    stale = (
        await db.execute(
            select(Coupon).where(
                Coupon.expiry_type == ExpiryType.DATE,
                Coupon.expires_at.is_not(None),
                Coupon.expires_at <= now,
            )
        )
    ).scalars().all()
    for coupon in stale:
        await db.delete(coupon)
    await db.commit()
    return {"deleted": len(stale)}
