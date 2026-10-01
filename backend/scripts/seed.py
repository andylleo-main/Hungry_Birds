"""Seed the demo stalls from a shell.

    PYTHONPATH=. python scripts/seed.py

Safe to re-run: stalls are matched by name and skipped if they already exist.

The stalls themselves live in app/core/demo_data.py, because a Railway service has
no shell to run this in. Its pre-deploy command is exec'd without one, so chaining
`alembic upgrade head && python scripts/seed.py` silently runs only the first half
and reports success. Setting SEED_DEMO_DATA=true is the way to seed a deployment;
this script is for a local database.

Creates no admin. Use BOOTSTRAP_ADMIN_EMAIL for that - see backend/.env.example.
"""

import asyncio
import sys

from app.core.demo_data import seed_demo_stalls
from app.db.session import async_session_factory


async def main() -> None:
    async with async_session_factory() as db:
        created = await seed_demo_stalls(db)

    for name in created:
        print(f"seeded {name}")
    if not created:
        print("Nothing to do - every demo stall already exists.")

    print("\nThese stalls are approved and open, so students see them straight")
    print("away. For an admin account set BOOTSTRAP_ADMIN_EMAIL to an address you")
    print("control - this deliberately creates none.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # a readable message instead of a traceback wall
        print(f"Seeding failed: {exc}")
        sys.exit(1)
