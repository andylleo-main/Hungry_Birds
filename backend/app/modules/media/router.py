import time

import cloudinary.utils
from fastapi import APIRouter, Depends, HTTPException, status

from app.core import limits
from app.core.config import Settings, get_settings
from app.core.ratelimit import limit_by_user
from app.core.deps import get_current_user
from app.modules.media.schemas import UploadSignature

router = APIRouter(prefix="/media", tags=["media"])


@router.get(
    "/signature",
    response_model=UploadSignature,
    dependencies=[Depends(limit_by_user("media_signature", *limits.MEDIA_SIGNATURE))],
)
async def get_upload_signature(
    _=Depends(get_current_user),
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
