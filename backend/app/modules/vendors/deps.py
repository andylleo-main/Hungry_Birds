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
    being replayed against another's endpoints. The rule that actually bites is
    role: a vendor account cannot place orders.

    **It does not check `is_approved`, deliberately.** A stall waiting on an
    admin still has to be able to build its menu, set its hours and name its
    delivery points - that is the work approval is granted *for* - and a stall
    that has been suspended still has to be able to finish the orders it already
    took. What approval gates is money and exposure: placing an order against the
    stall, paying for one, quoting cashback at it (`orders/router.py`,
    `payments/router.py`, `cashback/router.py`), and now anything that spends a
    resource outside this service - see `require_approved_vendor` below.
    """
    result = await db.execute(select(Vendor).where(Vendor.user_id == user.id))
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor profile not found")
    return vendor


async def require_approved_vendor(vendor: Vendor = Depends(get_own_vendor)) -> Vendor:
    """The caller's stall, but only once an admin has approved it.

    For the routes where an unapproved stall costs somebody something. The
    distinction matters because of how cheap a vendor account is: the merchant
    sign-in takes **any** email address on the internet - it has to, a stall
    owner has no institute address - so "signed in as a vendor" is a category
    anybody can join in two requests, and `POST /vendors/apply` adds a row to it.

    `get_own_vendor` is therefore roughly "anybody who asked", and it is the
    right gate for a stall editing its own menu, which harms nobody while the
    stall is invisible. It is the wrong gate for handing out a signed permit to
    upload into our Cloudinary account, which is what used to happen.

    A separate dependency rather than folding the check into `get_own_vendor`,
    so that the choice is made per route by somebody who looked at the route.
    """
    if not vendor.is_approved:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Your stall is waiting on approval. You'll be able to do this once it's live.",
        )
    return vendor
