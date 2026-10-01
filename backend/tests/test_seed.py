"""The demo seed must not hand out admin.

Pinned because the failure is silent and delayed. Seeding an admin account was
harmless for as long as /auth/admin/login was the only way into one, so nothing
looked wrong; it became "whoever receives mail at that address is an admin" only
when ADMIN_PASSWORD_HASH was removed to make admin login the ordinary OTP flow -
a change in a different file, made for an unrelated reason, possibly months later.

A comment does not survive that. A test does.
"""

import pytest

pytest.importorskip("sqlalchemy.ext.asyncio")


async def test_seeding_creates_no_admin(db):
    """Run the real seeder and check the admin count is unmoved.

    Deliberately runs it rather than reading the source: the question is what the
    database ends up holding, and a test that greps for a role name would pass
    against any number of other ways to grant one.
    """
    from sqlalchemy import func, select

    from app.db.models.user import User, UserRole
    from app.core.demo_data import seed_demo_stalls

    admins = select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
    before = (await db.execute(admins)).scalar_one()

    await seed_demo_stalls(db)

    db.expire_all()
    after = (await db.execute(admins)).scalar_one()

    assert after == before, (
        "seeding granted the admin role. Demo data must never do that: "
        "admin login is the ordinary OTP flow, so an admin row on an address we "
        "do not control is an admin anybody who receives that mail can claim."
    )


async def test_seeding_does_create_the_demo_stalls(db):
    """The other half - that removing the admin did not break what it is for."""
    from sqlalchemy import select

    from app.db.models.vendor import Vendor
    from app.core.demo_data import DEMO_STALLS, seed_demo_stalls

    names = {s["stall_name"] for s in DEMO_STALLS}

    # Which already existed, because the seeder skips those and must not rewrite
    # them - a stall the owner has since closed stays closed. So the flags below
    # are only this script's business for rows it actually inserts.
    existing = set(
        (
            await db.execute(select(Vendor.stall_name).where(Vendor.stall_name.in_(names)))
        ).scalars().all()
    )

    await seed_demo_stalls(db)

    db.expire_all()
    found = (
        await db.execute(select(Vendor.stall_name).where(Vendor.stall_name.in_(names)))
    ).scalars().all()
    assert set(found) == names

    # Approved and open, or students would not see them and the seed would be
    # pointless. Checked only on what this run created.
    fresh = names - existing
    if fresh:
        rows = (
            await db.execute(select(Vendor).where(Vendor.stall_name.in_(fresh)))
        ).scalars().all()
        assert all(v.is_approved and v.is_open for v in rows)


async def test_seeding_twice_does_not_duplicate(db):
    """It is run by hand against a live database, sometimes more than once."""
    from sqlalchemy import func, select

    from app.db.models.vendor import Vendor
    from app.core.demo_data import DEMO_STALLS, seed_demo_stalls

    await seed_demo_stalls(db)
    await seed_demo_stalls(db)

    db.expire_all()
    name = DEMO_STALLS[0]["stall_name"]
    count = (
        await db.execute(
            select(func.count()).select_from(Vendor).where(Vendor.stall_name == name)
        )
    ).scalar_one()
    assert count == 1
