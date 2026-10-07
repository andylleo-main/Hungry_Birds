"""What a student can do with a code: ask what it is worth, and see which they have.

Read-only. A coupon is *held* inside place_order, in the same transaction as the
order it discounts - an endpoint that could reserve a use on its own would be a
way to exhaust a code with a loop and no orders.
"""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.deps import ORDERING_ROLES, require_role
from app.core.ratelimit import limit_by_user
from app.db.models.coupon import Coupon, CouponAudience
from app.db.models.user import User
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.coupons import service
from app.modules.coupons.schemas import CouponCheckIn, CouponOut

router = APIRouter(prefix="/coupons", tags=["coupons"])


async def _stall_names(coupon: Coupon, db: AsyncSession) -> list[str]:
    """The names of the stalls a code is pinned to, or empty for every stall.

    Sorted, so a card showing two of three names shows the same two each time.
    """
    if coupon.all_stalls:
        return []
    pinned = await service.stalls_for(coupon.id, db)
    if not pinned:
        return []
    rows = await db.execute(
        select(Vendor.stall_name).where(Vendor.id.in_(pinned)).order_by(Vendor.stall_name)
    )
    return list(rows.scalars().all())


def _out(applied: service.Applied, stall_names: list[str]) -> CouponOut:
    c = applied.coupon
    return CouponOut(
        code=c.code,
        description=c.description,
        discount_type=c.discount_type,
        discount_value=c.discount_value,
        max_discount=c.max_discount,
        min_order_value=c.min_order_value,
        all_stalls=c.all_stalls,
        stall_names=stall_names,
        automatic=c.audience is CouponAudience.AUTOMATIC,
        discount=applied.discount,
    )


@router.post(
    "/check",
    response_model=CouponOut,
    dependencies=[Depends(limit_by_user("coupon_check", *limits.COUPON_CHECK))],
)
async def check(
    payload: CouponCheckIn,
    user: User = Depends(require_role(*ORDERING_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> CouponOut:
    """What this code is worth on this cart, or why it does not apply.

    **The same function place_order calls.** That is the whole reason this exists
    rather than the browser working the percentage out: a student shown one
    figure and charged against another stops trusting the app, and never reports
    it as a bug.

    Every refusal is a 400 carrying a sentence written for the person who typed
    the code - "that code is for a first order" rather than an error name - since
    it goes straight onto their screen.

    POST rather than GET because the code goes in the body: a code in a query
    string lands in server logs, proxy logs and browser history, and these are
    worth money to whoever reads them there.
    """
    try:
        coupon = await service.find(payload.code, db)
        applied = await service.assert_usable(
            coupon, user, payload.vendor_id, payload.subtotal, db
        )
    except service.CouponError as exc:
        raise exc.as_http()

    return _out(applied, await _stall_names(applied.coupon, db))


@router.get(
    "/available",
    response_model=list[CouponOut],
    dependencies=[Depends(limit_by_user("coupon_check", *limits.COUPON_CHECK))],
)
async def available(
    vendor_id: uuid.UUID | None = None,
    subtotal: Decimal = Query(default=Decimal("0"), ge=0, le=100000, decimal_places=2),
    user: User = Depends(require_role(*ORDERING_ROLES)),
    db: AsyncSession = Depends(get_db),
) -> list[CouponOut]:
    """Codes this student can use, best first.

    Only the ones an admin ticked *show in offers*, plus every automatic one -
    those have no code to type, so leaving them out would make them invisible
    until they applied themselves.

    Without a `vendor_id` this answers for the offers page, which has no stall in
    mind, and returns only site-wide codes: a stall-pinned one cannot be judged
    without knowing the cart it would apply to.
    """
    found = await service.available_for(user, vendor_id, subtotal, db)
    return [_out(a, await _stall_names(a.coupon, db)) for a in found]
