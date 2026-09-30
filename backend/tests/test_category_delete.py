"""Deleting a menu section must not delete the food in it.

The schema has always said ondelete="SET NULL" on menu_items.category_id, but
the ORM relationship carried cascade="all, delete-orphan", which wins:
SQLAlchemy issued DELETEs for the children before the database could apply its
own rule. Nothing in the app could delete a section, so it stayed hidden until
the merchant app grew the button.
"""

import uuid

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy.ext.asyncio")


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings

    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:
            await conn.rollback()
    except Exception:
        pytest.skip("needs a reachable Postgres")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _stall(db):
    from app.db.models.user import User, UserRole
    from app.db.models.vendor import Vendor

    user = User(email=f"cat.{uuid.uuid4().hex[:10]}@bitmesra.ac.in", role=UserRole.VENDOR)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    vendor = Vendor(user_id=user.id, stall_name=f"Cat {uuid.uuid4().hex[:5]}", is_approved=True)
    db.add(vendor)
    await db.commit()
    await db.refresh(vendor)
    return vendor


async def test_deleting_a_section_keeps_its_dishes(db):
    from sqlalchemy import select

    from app.db.models.menu import MenuCategory, MenuItem

    vendor = await _stall(db)
    category = MenuCategory(vendor_id=vendor.id, name="Momos")
    db.add(category)
    await db.commit()
    await db.refresh(category)

    item = MenuItem(vendor_id=vendor.id, category_id=category.id, name="Steamed", price=60)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    item_id = item.id

    await db.delete(category)
    await db.commit()
    db.expunge_all()

    survivor = (
        await db.execute(select(MenuItem).where(MenuItem.id == item_id))
    ).scalar_one_or_none()

    # The dish is the vendor's livelihood; the section is just a heading.
    assert survivor is not None, "deleting a section destroyed the food in it"
    assert survivor.category_id is None, "the dish should fall back to Uncategorised"
    assert survivor.name == "Steamed"


async def test_deleting_a_stall_does_remove_its_menu(db):
    """The other direction is still a real cascade - a stall that is gone
    should not leave menu rows behind."""
    from sqlalchemy import select

    from app.db.models.menu import MenuCategory, MenuItem

    vendor = await _stall(db)
    category = MenuCategory(vendor_id=vendor.id, name="Drinks")
    db.add(category)
    await db.commit()
    await db.refresh(category)
    db.add(MenuItem(vendor_id=vendor.id, category_id=category.id, name="Chai", price=15))
    await db.commit()

    await db.delete(vendor)
    await db.commit()
    db.expunge_all()

    left = (
        await db.execute(select(MenuItem).where(MenuItem.vendor_id == vendor.id))
    ).scalars().all()
    assert left == []
