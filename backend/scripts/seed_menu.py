"""Load a stall's menu from a CSV.

    PYTHONPATH=. python scripts/seed_menu.py \
        --email varunmalhotra94@gmail.com \
        --stall "Down South Cafe" \
        --csv scripts/data/down_south_cafe_menu.csv            # says what it would do

    ... --yes                                                  # does it

Point DATABASE_URL at the deployment you mean. Railway exposes a public
connection string for its Postgres service; there is no shell on the API service,
so this runs from your own machine.

**Dry run by default**, like every other script here. It prints the stall it
found or would create, every category, and a count of what it would add and what
it would leave alone - then does nothing until you pass --yes.

The CSV is `dish_name,category,price`, with a header row. Prices are rupees.
Blank lines are skipped; anything else malformed is an error naming the line,
because a menu half-loaded because row 94 had a stray comma is worse than one not
loaded at all. Nothing is written unless every row parses.

**Re-running is safe.** Items are matched on the stall's own menu by name,
case-insensitively, and an existing dish is left exactly as it is. There is no
unique index on item names - a stall may legitimately want two dishes with the
same name - so that matching is this script's job rather than the database's,
and getting it wrong would mean a second copy of all 169 dishes.

That also means this will not change a price by default. Use --update-prices
when you mean to, and read what it says about the approval flow first.
"""

import argparse
import asyncio
import csv
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select

from app.db.models.menu import MenuCategory, MenuItem
from app.db.models.user import User, UserRole
from app.db.models.vendor import Vendor
from app.db.session import async_session_factory
from app.modules.auth.service import normalize_email

# Matches the column the name is stored in. A dish longer than this would be
# truncated by the database, so it is refused here with the line number instead.
MAX_NAME = 255
MAX_PRICE = Decimal("100000")


class RowError(Exception):
    """A CSV line that cannot be trusted, named so it can be found and fixed."""


def read_menu(path: Path) -> list[tuple[str, str, Decimal]]:
    """Parse the whole file before anything touches the database.

    All-or-nothing on purpose: a menu that stopped loading at row 94 leaves
    somebody guessing which half is live, and the fix is a re-run that has to
    reason about what already landed.
    """
    rows: list[tuple[str, str, Decimal]] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = {"dish_name", "category", "price"} - set(reader.fieldnames or [])
        if missing:
            raise RowError(
                f"{path}: header is missing {', '.join(sorted(missing))} - "
                f"expected dish_name,category,price"
            )

        for line, raw in enumerate(reader, start=2):
            name = (raw.get("dish_name") or "").strip()
            category = (raw.get("category") or "").strip()
            price_text = (raw.get("price") or "").strip()

            if not name and not category and not price_text:
                continue  # a blank line, which spreadsheets add freely
            if not name:
                raise RowError(f"line {line}: no dish name")
            if len(name) > MAX_NAME:
                raise RowError(f"line {line}: dish name is longer than {MAX_NAME} characters")
            if not category:
                raise RowError(f"line {line}: {name!r} has no category")

            try:
                price = Decimal(price_text)
            except InvalidOperation:
                raise RowError(f"line {line}: {name!r} has price {price_text!r}, which is not a number")
            if price <= 0 or price > MAX_PRICE:
                raise RowError(f"line {line}: {name!r} is priced at {price}, which is out of range")

            rows.append((name, category, price))

    if not rows:
        raise RowError(f"{path}: no dishes in the file")
    return rows


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--email", required=True, help="the stall owner's sign-in address")
    parser.add_argument("--stall", help="stall name, used only when creating one")
    parser.add_argument("--yes", action="store_true", help="actually write")
    parser.add_argument(
        "--update-prices",
        action="store_true",
        help="also rewrite the price of dishes that already exist",
    )
    args = parser.parse_args()

    try:
        rows = read_menu(args.csv)
    except RowError as exc:
        print(f"error: {exc}")
        return 1
    except FileNotFoundError:
        print(f"error: no such file: {args.csv}")
        return 1

    print(f"{len(rows)} dishes in {args.csv}")

    email = normalize_email(args.email)

    async with async_session_factory() as db:
        owner = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        if owner is None:
            if not args.stall:
                print(
                    f"error: no account for {email}, and no --stall given to make one with."
                )
                return 1
            print(f"would create a vendor account for {email}")
            owner = User(email=email, role=UserRole.VENDOR)
            db.add(owner)
            await db.flush()
        elif owner.role is not UserRole.VENDOR:
            # Roles are immutable by design - an address that holds a customer
            # account cannot also sell - so this is a stop, not something to fix
            # by writing to the row.
            print(
                f"error: {email} is a {owner.role.value} account, not a vendor. "
                f"Roles are set when the account is created and never change; "
                f"the stall needs its own address."
            )
            return 1
        else:
            print(f"found the vendor account for {email}")

        vendor = (
            await db.execute(select(Vendor).where(Vendor.user_id == owner.id))
        ).scalar_one_or_none()

        if vendor is None:
            if not args.stall:
                print(f"error: {email} has no stall yet, and no --stall given to make one.")
                return 1
            print(f"would create the stall {args.stall!r}, **unapproved**")
            vendor = Vendor(user_id=owner.id, stall_name=args.stall)
            db.add(vendor)
            await db.flush()
        else:
            print(f"found the stall {vendor.stall_name!r} ({'live' if vendor.is_approved else 'not yet approved'})")

        # Both keyed case-insensitively, because the CSV is typed by a person and
        # "Burger" and "burger" are one section of one menu.
        existing_categories = {
            c.name.strip().lower(): c
            for c in (
                await db.execute(
                    select(MenuCategory).where(MenuCategory.vendor_id == vendor.id)
                )
            ).scalars().all()
        }
        existing_items = {
            i.name.strip().lower(): i
            for i in (
                await db.execute(select(MenuItem).where(MenuItem.vendor_id == vendor.id))
            ).scalars().all()
        }

        # First appearance in the file decides the order sections are shown in,
        # which is the order whoever wrote the CSV put them in.
        wanted_categories: list[str] = []
        for _, category, _price in rows:
            if category not in wanted_categories:
                wanted_categories.append(category)

        new_categories = 0
        for position, name in enumerate(wanted_categories):
            key = name.strip().lower()
            if key in existing_categories:
                continue
            category = MenuCategory(
                vendor_id=vendor.id, name=name, sort_order=position
            )
            db.add(category)
            existing_categories[key] = category
            new_categories += 1
        if new_categories:
            await db.flush()

        added = 0
        skipped: list[str] = []
        repriced: list[str] = []
        # Names queued for insert in this run. Kept apart from `existing_items`
        # rather than written into it, because a dict cannot say "I am about to
        # add this" with a value of None - `.get` would read that back as absent
        # and insert the dish a second time.
        queued: set[str] = set()

        for name, category_name, price in rows:
            key = name.strip().lower()
            category = existing_categories[category_name.strip().lower()]

            item = existing_items.get(key)
            if item is not None:
                was = Decimal(item.price)
                if args.update_prices and was != price:
                    item.price = price
                    repriced.append(f"{name}: {was} -> {price}")
                else:
                    skipped.append(name)
                continue

            if key in queued:
                # The same dish twice in one file. One menu entry, not two.
                skipped.append(name)
                continue

            db.add(
                MenuItem(
                    vendor_id=vendor.id,
                    category_id=category.id,
                    name=name,
                    price=price,
                    is_available=True,
                )
            )
            queued.add(key)
            added += 1

        print(
            f"\n{new_categories} new categories, {added} new dishes, "
            f"{len(skipped)} already on the menu"
        )
        if repriced:
            print(f"{len(repriced)} price changes:")
            for line in repriced[:20]:
                print(f"  {line}")
            if len(repriced) > 20:
                print(f"  ... and {len(repriced) - 20} more")
        elif skipped and not args.update_prices:
            print(
                "Existing dishes were left alone, prices included. "
                "Pass --update-prices to rewrite them."
            )

        if not args.yes:
            await db.rollback()
            print("\nDry run - nothing written. Re-run with --yes to do it.")
            return 0

        await db.commit()
        print("\nDone.")
        if not vendor.is_approved:
            print(
                f"{vendor.stall_name!r} is not approved, so nobody can see it yet. "
                f"Approve it in the admin panel, and open the stall from the "
                f"merchant app when it is ready to take orders."
            )
        return 0


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        raise SystemExit("needs Python 3.11+")
    raise SystemExit(asyncio.run(main()))
