import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.modules.auth.service import assert_allowed_domain, normalize_email


def settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        redis_url="redis://localhost:6379/0",
        jwt_secret="test-secret-long-enough-for-hs256-x",
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Student@BitMesra.ac.in", "student@bitmesra.ac.in"),
        ("  student@bitmesra.ac.in  ", "student@bitmesra.ac.in"),
        ("student+swiggy@bitmesra.ac.in", "student@bitmesra.ac.in"),
        ("student+a+b@bitmesra.ac.in", "student@bitmesra.ac.in"),
    ],
)
def test_normalize_email_collapses_case_and_plus_tags(raw, expected):
    assert normalize_email(raw) == expected


def test_plus_tagging_cannot_create_a_second_account():
    assert normalize_email("me+1@bitmesra.ac.in") == normalize_email("me@bitmesra.ac.in")


def test_institute_domain_is_allowed():
    assert_allowed_domain("student@bitmesra.ac.in", settings())


@pytest.mark.parametrize(
    "email",
    [
        "student@gmail.com",
        "student@notbitmesra.ac.in",
        "student@sub.bitmesra.ac.in",
        "student@bitmesra.ac.in.evil.com",
    ],
)
def test_other_domains_are_rejected(email):
    with pytest.raises(HTTPException) as exc:
        assert_allowed_domain(email, settings())
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgres://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),
        ("postgresql://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),
        ("postgresql+asyncpg://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),
    ],
)
def test_database_url_is_upgraded_to_the_async_driver(url, expected):
    config = Settings(database_url=url, redis_url="redis://localhost:6379/0", jwt_secret="test-secret-long-enough-for-hs256-x")
    assert config.database_url == expected


def test_otp_code_rejects_non_ascii_digits():
    """Unicode digits must be refused, not passed through.

    str.isdigit() is True for characters like the Arabic-Indic digits, so a
    naive check lets them reach secrets.compare_digest - which raises TypeError
    on any non-ASCII string. That turns a wrong code into a 500 instead of a
    clean rejection.
    """
    from pydantic import ValidationError

    from app.modules.auth.schemas import OTPVerify

    for bad in ("١٢٣٤٥٦", "12345٦", "12 456", "12345", "1234567", "abcdef"):
        with pytest.raises(ValidationError):
            OTPVerify(email="student@bitmesra.ac.in", code=bad)

    # The ordinary case still works.
    assert OTPVerify(email="student@bitmesra.ac.in", code="012345").code == "012345"
