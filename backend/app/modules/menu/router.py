import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.ratelimit import limit_by_user
from app.db.models.menu import MenuCategory, MenuItem
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.menu.schemas import (
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    ItemCreate,
    ItemOut,
    ItemUpdate,
)
from app.modules.vendors.deps import get_own_vendor

router = APIRouter(prefix="/vendors/me", tags=["menu"])


async def _get_own_category(vendor: Vendor, category_id: uuid.UUID, db: AsyncSession) -> MenuCategory:
    result = await db.execute(
        select(MenuCategory).where(MenuCategory.id == category_id, MenuCategory.vendor_id == vendor.id)
    )
    category = result.scalar_one_or_none()
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return category


async def _get_own_item(vendor: Vendor, item_id: uuid.UUID, db: AsyncSession) -> MenuItem:
    result = await db.execute(
        select(MenuItem).where(MenuItem.id == item_id, MenuItem.vendor_id == vendor.id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return item


@router.post(
    "/categories",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_user("menu_write", *limits.MENU_WRITE))],
)
async def create_category(
    payload: CategoryCreate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> CategoryOut:
    category = MenuCategory(vendor_id=vendor.id, **payload.model_dump())
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return CategoryOut.model_validate(category)


@router.get(
    "/categories",
    response_model=list[CategoryOut],
    dependencies=[Depends(limit_by_user("menu_read", *limits.PROFILE_READ))],
)
async def list_categories(
    vendor: Vendor = Depends(get_own_vendor), db: AsyncSession = Depends(get_db)
) -> list[CategoryOut]:
    result = await db.execute(
        select(MenuCategory).where(MenuCategory.vendor_id == vendor.id).order_by(MenuCategory.sort_order)
    )
    return [CategoryOut.model_validate(c) for c in result.scalars().all()]


@router.patch(
    "/categories/{category_id}",
    response_model=CategoryOut,
    dependencies=[Depends(limit_by_user("menu_write", *limits.MENU_WRITE))],
)
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> CategoryOut:
    category = await _get_own_category(vendor, category_id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    await db.commit()
    await db.refresh(category)
    return CategoryOut.model_validate(category)


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_by_user("menu_write", *limits.MENU_WRITE))],
)
async def delete_category(
    category_id: uuid.UUID,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> None:
    category = await _get_own_category(vendor, category_id, db)
    await db.delete(category)
    await db.commit()


@router.post(
    "/items",
    response_model=ItemOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_user("menu_write", *limits.MENU_WRITE))],
)
async def create_item(
    payload: ItemCreate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> ItemOut:
    if payload.category_id is not None:
        await _get_own_category(vendor, payload.category_id, db)

    item = MenuItem(vendor_id=vendor.id, **payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return ItemOut.model_validate(item)


@router.get(
    "/items",
    response_model=list[ItemOut],
    dependencies=[Depends(limit_by_user("menu_read", *limits.PROFILE_READ))],
)
async def list_items(
    vendor: Vendor = Depends(get_own_vendor), db: AsyncSession = Depends(get_db)
) -> list[ItemOut]:
    result = await db.execute(select(MenuItem).where(MenuItem.vendor_id == vendor.id))
    return [ItemOut.model_validate(i) for i in result.scalars().all()]


@router.patch(
    "/items/{item_id}",
    response_model=ItemOut,
    dependencies=[Depends(limit_by_user("menu_write", *limits.MENU_WRITE))],
)
async def update_item(
    item_id: uuid.UUID,
    payload: ItemUpdate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> ItemOut:
    item = await _get_own_item(vendor, item_id, db)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("category_id") is not None:
        await _get_own_category(vendor, changes["category_id"], db)
    for field, value in changes.items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return ItemOut.model_validate(item)


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_by_user("menu_write", *limits.MENU_WRITE))],
)
async def delete_item(
    item_id: uuid.UUID,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> None:
    item = await _get_own_item(vendor, item_id, db)
    await db.delete(item)
    await db.commit()
