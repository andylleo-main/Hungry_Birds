"""The admin password door: it must open for exactly one case and no other."""

import pytest

from app.modules.auth.passwords import (
    hash_password,
    verify_password,
    waste_time_like_a_verification,
)


def test_a_password_verifies_against_its_own_hash():
    encoded = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", encoded) is True


def test_the_wrong_password_does_not():
    encoded = hash_password("correct horse battery staple")
    for wrong in ("", "correct horse battery stapl", "CORRECT HORSE BATTERY STAPLE", "x"):
        assert verify_password(wrong, encoded) is False


def test_the_same_password_hashes_differently_every_time():
    """Salted, so two admins choosing the same password do not share a hash and
    a precomputed table is worthless."""
    a = hash_password("same password")
    b = hash_password("same password")
    assert a != b
    assert verify_password("same password", a)
    assert verify_password("same password", b)


def test_the_hash_carries_its_own_parameters():
    # So the work factor can be raised later without stranding existing hashes.
    encoded = hash_password("whatever")
    prefix, n, r, p, salt, key = encoded.split("$")
    assert prefix == "scrypt"
    assert int(n) >= 2**15 and int(r) >= 8 and int(p) >= 1


@pytest.mark.parametrize(
    "malformed",
    ["", "not-a-hash", "scrypt$", "scrypt$a$b$c$d$e", "bcrypt$32768$8$1$xx$yy", "$$$$$"],
)
def test_a_malformed_hash_fails_closed(malformed):
    """A half-pasted or corrupted environment variable must refuse the login,
    not raise into a 500 - and certainly not accept."""
    assert verify_password("anything", malformed) is False


def test_the_timing_decoy_runs_without_raising():
    # It exists so an unknown address is not measurably faster to reject than a
    # wrong password; all it has to do is cost the same and not blow up.
    waste_time_like_a_verification()
