import pytest
from fastapi import HTTPException

from app.modules.auth.service import normalize_phone


@pytest.mark.parametrize(
    "raw",
    [
        "9876543210",
        "+919876543210",
        "919876543210",
        "09876543210",
        "+91 98765 43210",
        "98765-43210",
        "  +91-98765 43210  ",
    ],
)
def test_the_shapes_people_actually_type_all_normalize_to_e164(raw):
    assert normalize_phone(raw) == "+919876543210"


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("123456789", "only 9 digits"),
        ("98765432100", "11 digits with no trunk prefix"),
        ("5876543210", "Indian mobiles never start with 5"),
        ("1234567890", "starts with 1"),
        ("", "empty"),
        ("not a phone", "no digits at all"),
        ("+1 415 555 0123", "US number, not an Indian mobile"),
    ],
)
def test_invalid_numbers_are_rejected(raw, reason):
    with pytest.raises(HTTPException) as exc:
        normalize_phone(raw)
    assert exc.value.status_code == 400, reason


def test_normalization_is_idempotent():
    once = normalize_phone("9876543210")
    assert normalize_phone(once) == once


def test_the_same_number_typed_differently_is_the_same_number():
    assert normalize_phone("09876543210") == normalize_phone("+91 98765 43210")
