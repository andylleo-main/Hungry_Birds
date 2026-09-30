import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import limits
from app.core.deps import get_current_user, require_audience, require_role
from app.core.ratelimit import limit_by_ip, limit_by_user
from app.core.security import TokenAudience
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.core.locations import label_for
from app.modules.fulfilment.schemas import LocationOut
from app.modules.fulfilment.service import enabled_codes
from app.modules.menu.schemas import CategoryWithItems, ItemOut
from app.modules.vendors.deps import get_own_vendor
from app.modules.vendors.schemas import VendorApply, VendorDetailOut, VendorOut, VendorUpdate

router = APIRouter(prefix="/vendors", tags=["vendors"])


@router.post(
    "/apply",
    response_model=VendorOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(limit_by_user("vendor_apply", *limits.VENDOR_APPLY)),
        Depends(require_audience(TokenAudience.MERCHANT)),
    ],
)
async def apply_as_vendor(
    payload: VendorApply,
    user: User = Depends(require_role(UserRole.VENDOR)),
    db: AsyncSession = Depends(get_db),
) -> VendorOut:
    """Describe the stall, for an account that already signed in as a vendor.

    This used to be how an account *became* a vendor - it set user.role itself,
    which meant any signed-in student could promote their own account and stop
    being able to order. The role is now settled when the account is created, on
    the vendor login route, so all this does is attach a stall to an account
    that is already one.
    """
    result = await db.execute(select(Vendor).where(Vendor.user_id == user.id))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vendor application already exists")

    vendor = Vendor(user_id=user.id, stall_name=payload.stall_name, description=payload.description)
    db.add(vendor)
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
    """Edit the stall's own description of itself.

    Each field is assigned by name rather than by looping over the payload. The
    loop was shorter, but it meant the set of things a vendor may write about
    themselves was decided by whatever happened to be on VendorUpdate - so
    adding a field there granted write access to it, silently, with no line in
    the diff that looked like an authorization change. `is_approved` on that
    schema by mistake would have let every stall approve itself.
    """
    changes = payload.model_dump(exclude_unset=True)

    if "stall_name" in changes:
        vendor.stall_name = changes["stall_name"]
    if "description" in changes:
        vendor.description = changes["description"]
    if "cover_image_url" in changes:
        vendor.cover_image_url = changes["cover_image_url"]
    if "is_open" in changes:
        vendor.is_open = changes["is_open"]

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

    # `enabled` is always True here: this list is the enabled set, and the field
    # exists so the merchant's settings screen and this one can share a type.
    delivery_locations = [
        LocationOut(code=code, label=label_for(code), enabled=True)
        for code in (await enabled_codes(vendor.id, db) if vendor.delivery_enabled else [])
    ]

    return VendorDetailOut(
        **VendorOut.model_validate(vendor).model_dump(),
        categories=categories,
        uncategorized_items=uncategorized,
        delivery_locations=delivery_locations,
    )
