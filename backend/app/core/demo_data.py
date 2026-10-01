"""The demo stalls a fresh deployment starts with.

Lives here rather than in scripts/ because it has two callers: the CLI at
scripts/seed.py, and the startup hook in app/main.py that runs when
SEED_DEMO_DATA is set. A Railway service has no shell, and its pre-deploy command
is exec'd without one - so `cmd && other-cmd` silently runs only the first, and a
script is not reachable there at all. An env-var-gated hook is the way in.

Deliberately creates no admin; see app/core/bootstrap.py for that. Seeding used to
make admin@bitmesra.ac.in, which was inert only while the admin password door
existed. The demo stall owners below are institute addresses too, but they are
vendor-role: a stall nobody can receive mail for is a stall nobody can sign into,
which is what a demo stall should be.
"""

from sqlalchemy import select

from app.db.models.menu import MenuCategory, MenuItem
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor
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


async def seed_demo_stalls(db) -> list[str]:
    """Create any demo stall that is missing. Returns the names created.

    Takes a session rather than opening one, so the caller decides the
    transaction: the CLI wants its own, the app's startup hook reuses the one it
    already has.
    """
    created: list[str] = []
    for stall in DEMO_STALLS:
        existing = await db.execute(
            select(Vendor).where(Vendor.stall_name == stall["stall_name"])
        )
        if existing.scalar_one_or_none() is not None:
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
        created.append(stall["stall_name"])

    await db.commit()

    return created
