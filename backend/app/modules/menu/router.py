import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.ratelimit import limit_by_user
from app.db.models.menu import MenuCategory, MenuItem, MenuItemVariant, PriceChangeKind
from app.db.models.vendor import Vendor
from app.db.session import get_db
from app.modules.menu.schemas import (
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    ItemCreate,
    ItemOut,
    ItemUpdate,
    PriceUpdate,
    VariantCreate,
    VariantOut,
    VariantUpdate,
)
from app.modules.menu.service import record_price_change, submit_price
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

    # Named, not **payload.model_dump(). The dict splat is the same hazard as
    # the assignment loop that used to be in update_item: it makes every field
    # ever added to ItemCreate writable without a line in the diff that looks
    # like an authorization change. pending_price must never appear here.
    item = MenuItem(
        vendor_id=vendor.id,
        name=payload.name,
        description=payload.description,
        price=payload.price,
        category_id=payload.category_id,
        image_url=payload.image_url,
    )
    db.add(item)
    await db.flush()
    # Creating a dish is deliberately not gated, so this price goes live at once.
    # Recorded anyway: add-new-then-delete-old is the one way round the gate, and
    # the history is what lets an admin notice it.
    record_price_change(
        db,
        vendor_id=vendor.id,
        kind=PriceChangeKind.CREATED,
        name=item.name,
        new_price=item.price,
        item_id=item.id,
    )
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

    # Assigned by name rather than looped over, matching update_my_vendor in
    # vendors/router.py and update_rider in riders/router.py, both of which carry
    # the same warning: a loop grants write access to every field added to the
    # schema later, silently, with nothing in the diff that reads as an
    # authorization change. This handler was the one that never got the
    # treatment, and adding pending_price to the model would have made it
    # self-writable. Price is not here at all - see set_item_price.
    if "name" in changes:
        item.name = changes["name"]
    if "description" in changes:
        item.description = changes["description"]
    if "category_id" in changes:
        item.category_id = changes["category_id"]
    if "image_url" in changes:
        item.image_url = changes["image_url"]
    if "is_available" in changes:
        item.is_available = changes["is_available"]

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


# --- prices, which are their own route because they are their own decision ----


async def _get_own_variant(
    vendor: Vendor, item_id: uuid.UUID, variant_id: uuid.UUID, db: AsyncSession
) -> MenuItemVariant:
    """Scoped through the item, so a stall cannot touch another stall's sizes."""
    item = await _get_own_item(vendor, item_id, db)
    result = await db.execute(
        select(MenuItemVariant).where(
            MenuItemVariant.id == variant_id, MenuItemVariant.item_id == item.id
        )
    )
    variant = result.scalar_one_or_none()
    if variant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Size not found")
    return variant


@router.put(
    "/items/{item_id}/price",
    response_model=ItemOut,
    dependencies=[Depends(limit_by_user("menu_write", *limits.MENU_WRITE))],
)
async def set_item_price(
    item_id: uuid.UUID,
    payload: PriceUpdate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> ItemOut:
    """Ask for a dish's price to change.

    Never writes the live price. The number goes into pending_price and an admin
    decides; students keep buying at the old one meanwhile, which is the product
    decision - a stall whose price is under review is not a stall that stops
    selling.
    """
    item = await _get_own_item(vendor, item_id, db)
    submit_price(item, payload.price, db, vendor_id=vendor.id, name=item.name)
    await db.commit()
    await db.refresh(item)
    return ItemOut.model_validate(item)


@router.delete(
    "/items/{item_id}/price",
    response_model=ItemOut,
    dependencies=[Depends(limit_by_user("menu_write", *limits.MENU_WRITE))],
)
async def withdraw_item_price(
    item_id: uuid.UUID,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> ItemOut:
    """Take back a price change nobody has looked at yet.

    A merchant who typed 2000 instead of 200 should not have to wait for a human
    to reject it before they can fix it.
    """
    item = await _get_own_item(vendor, item_id, db)
    if item.pending_price is not None:
        submit_price(item, item.price, db, vendor_id=vendor.id, name=item.name)
        await db.commit()
        await db.refresh(item)
    return ItemOut.model_validate(item)


# --- variants -----------------------------------------------------------------


@router.get(
    "/items/{item_id}/variants",
    response_model=list[VariantOut],
    dependencies=[Depends(limit_by_user("menu_read", *limits.PROFILE_READ))],
)
async def list_variants(
    item_id: uuid.UUID,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> list[VariantOut]:
    item = await _get_own_item(vendor, item_id, db)
    return [VariantOut.model_validate(v) for v in item.variants]


@router.post(
    "/items/{item_id}/variants",
    response_model=VariantOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_by_user("menu_write", *limits.MENU_WRITE))],
)
async def create_variant(
    item_id: uuid.UUID,
    payload: VariantCreate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> VariantOut:
    """Add a size. Its price goes live immediately.

    Not gated, mirroring "adding a dish is not gated" - a new size that cannot
    be sold until an admin wakes up is a size a stall will not bother adding.
    Recorded in the history for the same reason creations are.
    """
    item = await _get_own_item(vendor, item_id, db)

    clash = await db.execute(
        select(MenuItemVariant).where(
            MenuItemVariant.item_id == item.id,
            func.lower(MenuItemVariant.name) == payload.name.lower(),
        )
    )
    if clash.scalar_one_or_none() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"{item.name} already has a size called {payload.name}"
        )

    variant = MenuItemVariant(
        item_id=item.id,
        name=payload.name,
        price=payload.price,
        sort_order=payload.sort_order,
    )
    db.add(variant)
    await db.flush()
    record_price_change(
        db,
        vendor_id=vendor.id,
        kind=PriceChangeKind.CREATED,
        name=f"{item.name} - {variant.name}",
        new_price=variant.price,
        item_id=item.id,
        variant_id=variant.id,
    )
    await db.commit()
    await db.refresh(variant)
    return VariantOut.model_validate(variant)


@router.patch(
    "/items/{item_id}/variants/{variant_id}",
    response_model=VariantOut,
    dependencies=[Depends(limit_by_user("menu_write", *limits.MENU_WRITE))],
)
async def update_variant(
    item_id: uuid.UUID,
    variant_id: uuid.UUID,
    payload: VariantUpdate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> VariantOut:
    variant = await _get_own_variant(vendor, item_id, variant_id, db)
    changes = payload.model_dump(exclude_unset=True)
    # By name, for the reason spelled out in update_item.
    if "name" in changes:
        variant.name = changes["name"]
    if "sort_order" in changes:
        variant.sort_order = changes["sort_order"]
    if "is_available" in changes:
        variant.is_available = changes["is_available"]
    await db.commit()
    await db.refresh(variant)
    return VariantOut.model_validate(variant)


@router.put(
    "/items/{item_id}/variants/{variant_id}/price",
    response_model=VariantOut,
    dependencies=[Depends(limit_by_user("menu_write", *limits.MENU_WRITE))],
)
async def set_variant_price(
    item_id: uuid.UUID,
    variant_id: uuid.UUID,
    payload: PriceUpdate,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> VariantOut:
    """Gated exactly as an item's price is.

    Not a nicety: without it, a merchant whose item price is frozen adds a size
    called "Regular" at the number they wanted and sells at it immediately.
    """
    item = await _get_own_item(vendor, item_id, db)
    variant = await _get_own_variant(vendor, item_id, variant_id, db)
    submit_price(
        variant, payload.price, db, vendor_id=vendor.id, name=f"{item.name} - {variant.name}"
    )
    await db.commit()
    await db.refresh(variant)
    return VariantOut.model_validate(variant)


@router.delete(
    "/items/{item_id}/variants/{variant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limit_by_user("menu_write", *limits.MENU_WRITE))],
)
async def delete_variant(
    item_id: uuid.UUID,
    variant_id: uuid.UUID,
    vendor: Vendor = Depends(get_own_vendor),
    db: AsyncSession = Depends(get_db),
) -> None:
    variant = await _get_own_variant(vendor, item_id, variant_id, db)
    await db.delete(variant)
    await db.commit()
