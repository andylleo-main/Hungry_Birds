"""Seeds a few demo stalls and menus so the apps have something to show before
real vendors onboard.

Usage (from backend/, venv active, .env pointing at the target database):

    PYTHONPATH=. python scripts/seed.py

Safe to re-run: stalls are matched by name and skipped if they already exist.

Deliberately creates no admin. It used to make admin@bitmesra.ac.in, which was
inert only because the admin password door was the sole way into that account.
The moment admin login became the ordinary OTP flow - which is the point - that
row turned into "whoever receives mail at that address on the institute's domain
is an admin", on a domain we do not control. Seeding and un-gating admin login
were each harmless alone and an escalation together.

The demo stall owners below are the same kind of address and stay, because they
are vendor-role: a stall nobody can receive mail for is a stall nobody can sign
into, which is exactly what a demo stall should be.

To make a real admin, set BOOTSTRAP_ADMIN_EMAIL - see backend/.env.example.
"""

import asyncio
import sys

from sqlalchemy import select

from app.db.models.menu import MenuCategory, MenuItem
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor
from app.db.session import async_session_factory
from app.modules.auth.service import normalize_email

DEMO_STALLS = [
    {
        "email": "momopoint@bitmesra.ac.in",
        "stall_name": "Momo Point",
        "description": "Steamed and fried momos, right by the hostel gate",
        "sections": {
            "Momos": [
                ("Steamed Veg Momo", "8 pcs with spicy chutney", 60),
                ("Fried Veg Momo", "8 pcs, crispy", 80),
                ("Paneer Momo", "8 pcs, tandoori style", 100),
            ],
            "Beverages": [
                ("Masala Chai", None, 15),
                ("Cold Coffee", None, 50),
            ],
        },
    },
    {
        "email": "chaitapri@bitmesra.ac.in",
        "stall_name": "Chai Tapri",
        "description": "Chai, maggi and sandwiches near the main gate",
        "sections": {
            "Maggi": [
                ("Plain Maggi", None, 40),
                ("Cheese Maggi", "Loaded with cheese", 70),
                ("Egg Maggi", None, 60),
            ],
            "Snacks": [
                ("Veg Sandwich", "Grilled", 50),
                ("Samosa", "2 pcs", 20),
            ],
        },
    },
    {
        "email": "southexpress@bitmesra.ac.in",
        "stall_name": "South Express",
        "description": "Dosa, idli and filter coffee all day",
        "sections": {
            "Dosa": [
                ("Plain Dosa", None, 60),
                ("Masala Dosa", "With potato filling", 80),
                ("Cheese Dosa", None, 100),
            ],
            "Idli & More": [
                ("Idli Sambar", "3 pcs", 50),
                ("Filter Coffee", None, 25),
            ],
        },
    },
]


async def get_or_create_user(db, email: str, role: UserRole) -> User:
    normalized = normalize_email(email)
    result = await db.execute(select(User).where(User.email == normalized))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=normalized, role=role)
        db.add(user)
        await db.flush()
    elif user.role != role:
        user.role = role
    return user


async def seed() -> None:
    async with async_session_factory() as db:
        for stall in DEMO_STALLS:
            existing = await db.execute(
                select(Vendor).where(Vendor.stall_name == stall["stall_name"])
            )
            if existing.scalar_one_or_none() is not None:
                print(f"skipping {stall['stall_name']} (already seeded)")
                continue

            owner = await get_or_create_user(db, stall["email"], UserRole.VENDOR)
            vendor = Vendor(
                user_id=owner.id,
                stall_name=stall["stall_name"],
                description=stall["description"],
                is_approved=True,
                is_open=True,
            )
            db.add(vendor)
            await db.flush()

            for order, (section, items) in enumerate(stall["sections"].items()):
                category = MenuCategory(vendor_id=vendor.id, name=section, sort_order=order)
                db.add(category)
                await db.flush()
                for name, description, price in items:
                    db.add(
                        MenuItem(
                            vendor_id=vendor.id,
                            category_id=category.id,
                            name=name,
                            description=description,
                            price=price,
                        )
                    )
            print(f"seeded {stall['stall_name']}")

        await db.commit()

    print("\nDone. These stalls are approved and open, so they are visible to")
    print("students straight away. For an admin account, set BOOTSTRAP_ADMIN_EMAIL")
    print("to an address you control - this script deliberately creates none.")


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    except Exception as exc:  # surface a readable message instead of a traceback wall
        print(f"Seeding failed: {exc}")
        sys.exit(1)
