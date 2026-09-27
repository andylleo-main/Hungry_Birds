"""Input constraints, one test per thing that used to get through.

Every case here was verified against a running API before being fixed: the
money ones were accepted outright, the rest reached Postgres and came back as
a 500 from a column-length or integer-range violation. A 500 on an endpoint a
client can reach at will is both a bug and noise that hides real faults.
"""

import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import UpdateMe
from app.modules.menu.schemas import CategoryCreate, ItemCreate, ItemUpdate
from app.modules.orders.schemas import OrderCreate
from app.modules.vendors.schemas import VendorApply, VendorUpdate

ITEM = "11111111-1111-1111-1111-111111111111"


# --- money ------------------------------------------------------------------


def test_a_menu_item_cannot_be_priced_below_zero():
    """The one that was not merely untidy.

    A negative price was accepted and stored, and because orders are totalled
    from the menu snapshot, adding such an item to an order pulled the total
    down with it.
    """
    with pytest.raises(ValidationError):
        ItemCreate(name="Free lunch", price=-100)


def test_a_price_larger_than_the_column_is_refused():
    # Numeric(10, 2) tops out below this; it used to raise from Postgres.
    with pytest.raises(ValidationError):
        ItemCreate(name="Gold momo", price=999_999_999_999)


def test_a_price_cannot_carry_sub_paisa_precision():
    with pytest.raises(ValidationError):
        ItemCreate(name="Odd", price="1.23456789")


def test_ordinary_prices_are_fine():
    assert ItemCreate(name="Momo", price="60.50").price == pytest.approx(60.50)
    assert ItemCreate(name="Water", price=0).price == 0


# --- text lengths match their columns ---------------------------------------


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (ItemCreate, "name"),
        (CategoryCreate, "name"),
        (VendorApply, "stall_name"),
        (UpdateMe, "full_name"),
    ],
)
def test_names_are_capped_at_the_column_width(model, field):
    payload = {field: "x" * 5000}
    if model is ItemCreate:
        payload["price"] = 10
    with pytest.raises(ValidationError):
        model(**payload)


def test_a_blank_name_is_not_a_name():
    # Whitespace is stripped first, so "   " is empty and refused rather than
    # stored as a stall with an invisible title.
    with pytest.raises(ValidationError):
        VendorApply(stall_name="   ")


def test_names_are_stripped():
    assert VendorApply(stall_name="  Momo Point  ").stall_name == "Momo Point"


def test_an_order_note_is_capped():
    with pytest.raises(ValidationError):
        OrderCreate(
            vendor_id=ITEM,
            items=[{"menu_item_id": ITEM, "quantity": 1}],
            note="n" * 3000,
        )


# --- urls -------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["javascript:alert(document.cookie)", "data:text/html,<script>", "ftp://x/y", "x" * 5000],
)
def test_image_urls_must_be_http(bad):
    """These end up in an <img src> on every customer's screen, so the scheme
    is not something a vendor gets to choose freely."""
    with pytest.raises(ValidationError):
        ItemUpdate(image_url=bad)
    with pytest.raises(ValidationError):
        VendorUpdate(cover_image_url=bad)


def test_a_normal_image_url_passes():
    url = "https://res.cloudinary.com/demo/image/upload/momo.jpg"
    assert ItemUpdate(image_url=url).image_url == url


# --- sizes that cost the server something ------------------------------------


def test_an_order_cannot_carry_thousands_of_lines():
    """Each line is priced with its own query, so the list length is a
    multiplier on the work one request can demand."""
    with pytest.raises(ValidationError):
        OrderCreate(
            vendor_id=ITEM,
            items=[{"menu_item_id": ITEM, "quantity": 1}] * 2000,
        )


def test_an_order_needs_at_least_one_line():
    with pytest.raises(ValidationError):
        OrderCreate(vendor_id=ITEM, items=[])


def test_sort_order_stays_inside_a_32_bit_integer():
    with pytest.raises(ValidationError):
        CategoryCreate(name="Mains", sort_order=10**18)


def test_quantity_is_bounded_both_ways():
    for bad in (0, -1, 10**9):
        with pytest.raises(ValidationError):
            OrderCreate(vendor_id=ITEM, items=[{"menu_item_id": ITEM, "quantity": bad}])
