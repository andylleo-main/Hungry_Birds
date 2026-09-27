import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import limits
from app.core.deps import get_current_user
from app.core.ratelimit import limit_by_ip, limit_by_user
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.menu.schemas import CategoryWithItems, ItemOut
from app.modules.vendors.deps import get_own_vendor
from app.modules.vendors.schemas import VendorApply, VendorDetailOut, VendorOut, VendorUpdate

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.post(
    "/apply",
    response_model=VendorOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_user("vendor_apply", *limits.VENDOR_APPLY))],
)
async def apply_as_vendor(
    payload: VendorApply,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VendorOut:
    if user.role == UserRole.VENDOR:
        result = await db.execute(select(Vendor).where(Vendor.user_id == user.id))
        if result.scalar_one_or_none() is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vendor application already exists")

    vendor = Vendor(user_id=user.id, stall_name=payload.stall_name, description=payload.description)
    db.add(vendor)
    user.role = UserRole.VENDOR
    await db.commit()
    await db.refresh(vendor)
    return VendorOut.model_validate(vendor)


@router.get(
    "/me",
    response_model=VendorOut,
    dependencies=[Depends(limit_by_user("vendor_read", *limits.PROFILE_READ))],
)
async def get_my_vendor(vendor: Vendor = Depends(get_own_vendor)) -> VendorOut:
    return VendorOut.model_validate(vendor)


@router.patch(
    "/me",
    response_model=VendorOut,
    dependencies=[Depends(limit_by_user("vendor_update", *limits.VENDOR_UPDATE))],
)
async def update_my_vendor(
    payload: VendorUpdate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> VendorOut:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(vendor, field, value)
    await db.commit()
    await db.refresh(vendor)
    return VendorOut.model_validate(vendor)


@router.get(
    "",
    response_model=list[VendorOut],
    dependencies=[Depends(limit_by_ip("public_browse", *limits.PUBLIC_BROWSE))],
)
async def list_vendors(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VendorOut]:
    result = await db.execute(
        select(Vendor).where(Vendor.is_approved.is_(True)).order_by(Vendor.stall_name)
    )
    return [VendorOut.model_validate(v) for v in result.scalars().all()]


@router.get(
    "/{vendor_id}",
    response_model=VendorDetailOut,
    dependencies=[Depends(limit_by_ip("public_browse", *limits.PUBLIC_BROWSE))],
)
async def get_vendor_detail(
    vendor_id: uuid.UUID,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VendorDetailOut:
    result = await db.execute(
        select(Vendor)
        .where(Vendor.id == vendor_id, Vendor.is_approved.is_(True))
        .options(selectinload(Vendor.categories), selectinload(Vendor.items))
    )
    vendor = result.scalar_one_or_none()
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")

    items_by_category: dict[uuid.UUID, list] = {}
    uncategorized = []
    for item in vendor.items:
        if item.category_id is None:
            uncategorized.append(ItemOut.model_validate(item))
        else:
            items_by_category.setdefault(item.category_id, []).append(ItemOut.model_validate(item))

    categories = [
        CategoryWithItems(
            id=c.id,
            name=c.name,
            sort_order=c.sort_order,
            items=items_by_category.get(c.id, []),
        )
        for c in vendor.categories
    ]

    return VendorDetailOut(
        **VendorOut.model_validate(vendor).model_dump(),
        categories=categories,
        uncategorized_items=uncategorized,
    )
