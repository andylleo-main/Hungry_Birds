import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.deps import require_role
from app.core.ratelimit import limit_by_user
from app.db.models.user import UserRole
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.vendors.schemas import VendorOut

router = APIRouter(
    prefix="/admin/vendors", tags=["admin"], dependencies=[Depends(require_role(UserRole.ADMIN))]
)


@router.get(
    "",
    response_model=list[VendorOut],
    dependencies=[Depends(limit_by_user("admin_read", *limits.ADMIN_READ))],
)
async def list_vendors_for_admin(
    pending_only: bool = False, db: AsyncSession = Depends(get_db)
) -> list[VendorOut]:
    query = select(Vendor)
    if pending_only:
        query = query.where(Vendor.is_approved.is_(False))
    result = await db.execute(query.order_by(Vendor.created_at))
    return [VendorOut.model_validate(v) for v in result.scalars().all()]


async def _get_vendor_or_404(vendor_id: uuid.UUID, db: AsyncSession) -> Vendor:
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")
    return vendor


@router.post(
    "/{vendor_id}/approve",
    response_model=VendorOut,
    dependencies=[Depends(limit_by_user("admin_write", *limits.ADMIN_WRITE))],
)
async def approve_vendor(vendor_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> VendorOut:
    vendor = await _get_vendor_or_404(vendor_id, db)
    vendor.is_approved = True
    await db.commit()
    await db.refresh(vendor)
    return VendorOut.model_validate(vendor)


@router.post(
    "/{vendor_id}/suspend",
    response_model=VendorOut,
    dependencies=[Depends(limit_by_user("admin_write", *limits.ADMIN_WRITE))],
)
async def suspend_vendor(vendor_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> VendorOut:
    vendor = await _get_vendor_or_404(vendor_id, db)
    vendor.is_approved = False
    vendor.is_open = False
    await db.commit()
    await db.refresh(vendor)
    return VendorOut.model_validate(vendor)
