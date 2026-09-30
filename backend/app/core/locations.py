"""The campus places a stall can deliver to.

A fixed catalogue in code rather than a table, because these are eighteen
buildings on one campus - they are not user data, nobody adds one through the
API, and putting them in Postgres would mean a join and a seeding step to
express something that never changes between deploys.

Per-vendor state is stored as the set of locations a stall has switched *off*
(see VendorDisabledLocation). Every location is therefore on by default: a new
stall needs no seeding, the stalls that already existed need no backfill, and a
twentieth location added here is immediately available everywhere. The cost of
that choice is that a code removed from this dict leaves orphan rows behind,
which is why lookups tolerate an unknown code instead of raising.
"""

# Ordered as someone would read them off a campus map, because this ordering is
# what the merchant app and the checkout page render.
DELIVERY_LOCATIONS: dict[str, str] = {
    **{f"hostel_{n}": f"Hostel {n}" for n in range(1, 14)},
    "rs_hostel": "RS Hostel",
    "rnd_building": "R&D Building",
    "biotech_dept": "Biotech Department",
    "lecture_hall_1": "Lecture Hall 1",
    "ic_arena": "IC Arena",
}

# String(32) in the database; assert it here so adding a longer code fails at
# import in the test suite rather than as an insert error in production.
MAX_LOCATION_CODE_LENGTH = 32
assert all(len(code) <= MAX_LOCATION_CODE_LENGTH for code in DELIVERY_LOCATIONS)


def is_known_location(code: str) -> bool:
    return code in DELIVERY_LOCATIONS


def label_for(code: str) -> str:
    """The human name for a code.

    Falls back to the code itself rather than raising: a stall may hold a
    disabled row, or an old order may hold a delivery address, for a location
    that has since been removed from the catalogue above. Neither should turn
    into a 500 when someone opens their order history.
    """
    return DELIVERY_LOCATIONS.get(code, code)
