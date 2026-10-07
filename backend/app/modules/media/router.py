import time

import cloudinary.utils
from fastapi import APIRouter, Depends, HTTPException, status

from app.core import limits
from app.core.config import Settings, get_settings
from app.core.ratelimit import limit_by_user
from app.modules.media.schemas import UploadSignature
from app.modules.vendors.deps import require_approved_vendor

router = APIRouter(prefix="/media", tags=["media"])


@router.get(
    "/signature",
    response_model=UploadSignature,
    dependencies=[Depends(limit_by_user("media_signature", *limits.MEDIA_SIGNATURE))],
)
async def get_upload_signature(
    # Approved stalls only.
    #
    # Each call is a signed permit to upload into our Cloudinary account, and the
    # only client that ever needs one is the merchant app putting a photo on a
    # menu item. While signing up required an institute address, handing these to
    # every authenticated user was merely untidy. Now that a stall can register
    # with any email address, "any authenticated user" is "anyone", and the free
    # tier is something a stranger could fill.
    #
    # This used to depend on `get_own_vendor`, which narrowed "anyone signed in"
    # to "anyone who signed up and pressed Apply" - barely narrower, since both
    # are two requests away from a stranger with any inbox. Approval is the first
    # point at which a human has looked, which is what a permit to spend somebody
    # else's quota should wait for.
    _=Depends(require_approved_vendor),
    settings: Settings = Depends(get_settings),
) -> UploadSignature:
    if not settings.cloudinary_api_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Image uploads are not configured yet"
        )

    timestamp = int(time.time())
    params_to_sign = {"timestamp": timestamp, "folder": settings.cloudinary_upload_folder}
    signature = cloudinary.utils.api_sign_request(params_to_sign, settings.cloudinary_api_secret)

    return UploadSignature(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        timestamp=timestamp,
        signature=signature,
        folder=settings.cloudinary_upload_folder,
    )
