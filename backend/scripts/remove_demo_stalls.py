"""Delete the three demo stalls, and everything that hangs off them.

    PYTHONPATH=. python scripts/remove_demo_stalls.py            # says what it would do
    PYTHONPATH=. python scripts/remove_demo_stalls.py --yes      # does it

Point DATABASE_URL at the deployment you mean. Railway exposes a public
connection string for its Postgres service; there is no shell on the API
service, so this runs from your own machine.

**This is not reversible and it is not only stalls.** `orders.vendor_id` is ON
DELETE CASCADE, so removing a demo stall removes every order ever placed against
it, and `payments.order_id` cascades from there - so the payment rows for those
orders go too. On a stall that has only ever served test orders that is the
point. Read the dry run before passing --yes.

Matched on the owner's email rather than the stall name, because a name can be
edited from the merchant app and an address cannot. A stall somebody renamed is
still the demo stall; a real stall that happens to be called "Momo Point" is not.
"""

import asyncio
import sys

from sqlalchemy import func, select

from app.db.models.menu import MenuItem
from app.db.models.order import Order
from app.db.models.user import User
from app.db.models.vendor import Vendor
from app.db.session import async_session_factory
from app.modules.auth.service import normalize_email

# The addresses app/core/demo_data.py used before it was deleted. Written out
# here rather than imported, because the point of this script is to clean up
# after a module that no longer exists.
DEMO_OWNER_EMAILS = [
    "momopoint@bitmesra.ac.in",
    "chaitapri@bitmesra.ac.in",
    "southexpress@bitmesra.ac.in",
]


async def main() -> None:
    commit = "--yes" in sys.argv

    async with async_session_factory() as db:
        wanted = [normalize_email(e) for e in DEMO_OWNER_EMAILS]
        owners = (
            await db.execute(select(User).where(User.email.in_(wanted)))
        ).scalars().all()

        if not owners:
            print("No demo owner accounts found. Nothing to do.")
            return

        total_orders = 0
        for owner in owners:
            vendor = (
                await db.execute(select(Vendor).where(Vendor.user_id == owner.id))
            ).scalar_one_or_none()

            if vendor is None:
                print(f"{owner.email}: account with no stall")
                continue

            items = await db.scalar(
                select(func.count()).select_from(MenuItem).where(MenuItem.vendor_id == vendor.id)
            )
            orders = await db.scalar(
                select(func.count()).select_from(Order).where(Order.vendor_id == vendor.id)
            )
            total_orders += orders or 0
            print(
                f"{vendor.stall_name} ({owner.email}): "
                f"{items or 0} menu items, {orders or 0} orders"
            )

        if not commit:
            print(
                f"\nDry run. {len(owners)} account(s) would be deleted, taking "
                f"{total_orders} order(s) and their payment rows with them.\n"
                "Re-run with --yes to do it."
            )
            return

        for owner in owners:
            await db.delete(owner)
        await db.commit()
        print(f"\nDeleted {len(owners)} demo account(s) and everything under them.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # a readable message instead of a traceback wall
        print(f"Failed: {exc}")
        sys.exit(1)
