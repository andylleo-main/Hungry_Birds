"""Reusable validated field types.

Pydantic was already parsing every request body, but parsing is not the same as
validating: a field typed `str` accepts a five-thousand-character string, and a
field typed `Decimal` accepts a negative one. Both went straight through to
Postgres, where the first became a 500 from a column-length violation and the
second became a menu item priced at minus one hundred rupees.

These types are kept together rather than spread across the schema modules so
the input policy can be read in one place - the same reason the rate limits
live in limits.py. Each one is sized to the database column behind it, so a
value that would fail at the database fails at the edge instead, as a 422 that
names the field.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints

# --- Text -------------------------------------------------------------------
# 255 matches the String(255) columns these land in: stall names, item names,
# category names, a person's name.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]

# Free text with no column limit (Text), so the bound here is about abuse
# rather than the schema: nothing legitimate needs more, and unbounded text is
# free storage for anyone who wants it.
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]

# Order note -> String(500).
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


def _http_url(value: str) -> str:
    """Only http(s), so a stored URL cannot carry a scheme that does something
    when a client follows it.

    Images are uploaded to Cloudinary and the returned URL is handed back to
    us, so in normal use this is always https. It is validated because the
    field is client-supplied and ends up in an <img src> on every customer's
    screen - `javascript:` and `data:` have no business there.
    """
    if not value.startswith(("http://", "https://")):
        raise ValueError("must be an http(s) URL")
    return value


# 1024 matches the String(1024) image columns.
ImageUrl = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
    AfterValidator(_http_url),
]

# --- Money ------------------------------------------------------------------
# The column is Numeric(10, 2). Negative was the real hole: a vendor could
# price an item below zero and drag an order's total down with it. The ceiling
# is far above any campus food item while staying inside what the column holds.
Money = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("100000"), decimal_places=2)]

# --- Small integers ---------------------------------------------------------
# Postgres integer is 32-bit; anything larger raised instead of being rejected.
SortOrder = Annotated[int, Field(ge=0, le=10_000)]

# One person's order. The ceiling matters because every line costs a database
# round trip when the order is priced, so an unbounded list is a way to turn
# one request into thousands of queries.
MAX_ORDER_LINES = 50
