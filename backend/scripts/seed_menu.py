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

That also means nothing already on the menu is changed by default. Two flags
change that, and both write `price` directly - which is the merchant app's
pending-price approval flow bypassed, so neither is the default:

    --update-prices   the price of an existing dish, and nothing else
    --replace         the price **and** the section: bring the menu in line
                      with the file

**--replace updates rows in place; it does not delete and recreate them.** That
is deliberate. `menu_item_variants.item_id` is ON DELETE CASCADE, so deleting a
dish takes its half/full variants with it - and this file carries one price per
dish and no variant information, so there would be nothing to rebuild them from.
Updating in place also keeps the dish's photograph, its prep time, any price
change waiting on an admin, and its id, which is what a customer's saved cart
points at.

Neither flag removes anything. A dish on the menu that the file does not mention
is reported and left alone: a CSV is one person's list, not a claim about the
whole menu.
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
    parser.add_argument(
        "--replace",
        action="store_true",
        help="bring existing dishes fully in line with the file: price and section",
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
        # For naming the section an existing dish currently sits in, when that
        # disagrees with the file.
        category_names = {c.id: c.name for c in existing_categories.values() if c.id}

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
        matched = 0
        skipped: list[str] = []
        repriced: list[str] = []
        # Where the file and the live menu already disagree. Never acted on
        # silently - a stall that is open has prices somebody set on purpose.
        disagree: list[str] = []
        misplaced: list[str] = []
        moved: list[str] = []
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
                matched += 1
                was = Decimal(item.price)
                # Reported whether or not anything is done about it. A stall that
                # is already live has a menu somebody has been editing, and a
                # file that silently disagrees with it is the thing worth seeing
                # before 150 more dishes land next to it.
                if was != price:
                    disagree.append(f"{name}: menu says {was}, file says {price}")
                here = category_names.get(item.category_id)
                if here is None or here.strip().lower() != category_name.strip().lower():
                    misplaced.append(
                        f"{name}: in {here or 'no section'}, file says {category_name}"
                    )

                touched = False
                if (args.update_prices or args.replace) and was != price:
                    item.price = price
                    repriced.append(f"{name}: {was} -> {price}")
                    touched = True
                if args.replace and item.category_id != category.id:
                    item.category_id = category.id
                    moved.append(f"{name}: {here or 'no section'} -> {category_name}")
                    touched = True
                if not touched:
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
            f"{matched} already on the menu"
        )
        def _listing(title: str, lines: list[str]) -> None:
            if not lines:
                return
            print(f"\n{title} ({len(lines)}):")
            for line in lines[:30]:
                print(f"  {line}")
            if len(lines) > 30:
                print(f"  ... and {len(lines) - 30} more")

        if args.replace:
            _listing("Prices being brought in line with the file", repriced)
            _listing("Dishes being moved to the file's section", moved)
            if not repriced and not moved:
                print("\nEvery dish already on the menu matches the file.")
        else:
            _listing("Priced differently on the live menu", disagree)
            _listing("In a different section from the file", misplaced)

            if repriced:
                _listing("Prices being rewritten", repriced)
            elif disagree:
                print(
                    "\nThose prices are being left as they are. --replace brings "
                    "them in line with the file, price and section both; "
                    "--update-prices does the price only. Either writes `price` "
                    "directly, which is the merchant app's approval flow bypassed."
                )
            elif skipped:
                print("\nExisting dishes were left alone, and all of them match the file.")

            if misplaced:
                print(
                    "Sections are only changed by --replace. Otherwise move them "
                    "from the merchant app."
                )

        # Dishes the stall sells that the file says nothing about. Reported and
        # never removed: a CSV is one person's list, not a claim about the whole
        # menu, and deleting on that assumption is not a thing to do quietly.
        in_file = {name.strip().lower() for name, _c, _p in rows}
        extra = sorted(
            item.name for key, item in existing_items.items() if key not in in_file
        )
        if extra:
            _listing("On the menu but not in the file - left alone", extra)

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
