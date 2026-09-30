from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_audience, require_role
from app.core.security import TokenAudience
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor
from app.db.session import get_db


async def get_own_vendor(
    user: User = Depends(require_role(UserRole.VENDOR)),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_audience(TokenAudience.MERCHANT)),
) -> Vendor:
    """The stall belonging to the caller.

    The single gate in front of every vendor endpoint - menu, orders, stall
    profile, fulfilment, upload permits - which is why the merchant-app audience
    check lives here rather than on each router. Put it on the routers and the
    next vendor endpoint someone adds is the one that forgets it.

    It is worth being honest about what that check does and does not do. It
    cannot tell the Android app from curl pretending to be it; there is no client
    attestation. What it does is stop a session belonging to one Hungry Birds app
    being replayed against another's endpoints. The rules that actually bite are
    role - a vendor account cannot place orders - and is_approved.
    """
    result = await db.execute(select(Vendor).where(Vendor.user_id == user.id))
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor profile not found")
    return vendor
