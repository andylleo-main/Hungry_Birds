from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.ratelimit import limit_by_user
from app.db.models.device import VendorDevice
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.notifications.schemas import DeviceOut, DeviceRegister
from app.modules.notifications.service import register_device
from app.modules.vendors.deps import get_own_vendor

# Lives in the vendor namespace beside menu, orders and fulfilment, and inherits
# get_own_vendor's merchant-app audience check with it.
router = APIRouter(prefix="/vendors/me/devices", tags=["notifications"])


@router.post(
    "",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_user("device_write", *limits.DEVICE_WRITE))],
)
async def register(
    payload: DeviceRegister,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> DeviceOut:
    """Tell us where to push this stall's new orders.

    The merchant app calls this on every start, not only the first: Firebase
    rotates a registration token on reinstall, on app data being cleared, and
    occasionally on its own. A stall whose token has quietly rotated simply stops
    getting notifications, with nothing to see.
    """
    device = await register_device(vendor.id, payload.fcm_token, payload.platform, db)
    return DeviceOut.model_validate(device)


@router.delete(
    "/{fcm_token}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_by_user("device_write", *limits.DEVICE_WRITE))],
)
async def unregister(
    fcm_token: str,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Stop pushing to this phone - called on sign-out.

    Scoped to the caller's own stall, so holding somebody else's token is not a
    way to silence their notifications. Deleting something that is not there is
    a 204 as well, so signing out twice is not an error.
    """
    await db.execute(
        delete(VendorDevice).where(
            VendorDevice.fcm_token == fcm_token,
            VendorDevice.vendor_id == vendor.id,
        )
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
