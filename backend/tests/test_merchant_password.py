"""Stall owners signing in with a password instead of waiting for a code.

The shape worth holding onto: the first sign-in is still an email code, setting
a password is an authenticated action that follows it, and "forgot password" is
therefore the same email code again rather than a reset flow of its own. There
are no reset tokens in this system and these tests are part of why.
"""

import uuid

import pytest

pytest.importorskip("httpx")


async def _sixty_seconds_later(email: str) -> None:
    """Clear the one-code-a-minute cooldown for an address.

    Not a weakening of the rule - the rule is right, and a test that disabled it
    would stop checking the routes as they really run. This stands in for the
    minute passing, which is the only thing between a merchant and their second
    code. Several tests below sign in twice on purpose, because signing in twice
    is exactly what "I forgot my password" looks like.
    """
    from app.core.redis import get_redis
    from app.modules.auth.service import _rate_limit_key
    from app.modules.auth.service import normalize_email

    redis = get_redis()
    await redis.delete(_rate_limit_key(normalize_email(email)))


async def _otp_signin(client, email: str) -> dict:
    """Sign in as a stall owner the long way, through the real OTP routes."""
    await _sixty_seconds_later(email)
    requested = await client.post("/auth/vendor/otp/request", json={"email": email})
    assert requested.status_code == 200, requested.text
    code = requested.json()["debug_code"]
    assert code, "OTP_DEBUG_ECHO must be on for the test settings"

    verified = await client.post(
        "/auth/vendor/otp/verify", json={"email": email, "code": code}
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _email() -> str:
    return f"stall.{uuid.uuid4().hex[:10]}@gmail.com"


# --- the flow a merchant actually walks -------------------------------------


async def test_a_new_stall_has_no_password_until_it_sets_one(client):
    email = _email()
    tokens = await _otp_signin(client, email)

    state = await client.get("/auth/vendor/password", headers=_bearer(tokens["access_token"]))
    assert state.status_code == 200
    assert state.json()["is_set"] is False


async def test_setting_a_password_then_signing_in_with_it(client):
    """The whole point of the feature, end to end."""
    email = _email()
    tokens = await _otp_signin(client, email)

    set_it = await client.put(
        "/auth/vendor/password",
        headers=_bearer(tokens["access_token"]),
        json={"password": "chai-and-samosa"},
    )
    assert set_it.status_code == 200, set_it.text
    # Setting a password hands back a working session, so the merchant is not
    # signed out by the act of setting one.
    assert set_it.json()["access_token"]

    state = await client.get(
        "/auth/vendor/password", headers=_bearer(set_it.json()["access_token"])
    )
    assert state.json()["is_set"] is True

    again = await client.post(
        "/auth/vendor/login", json={"email": email, "password": "chai-and-samosa"}
    )
    assert again.status_code == 200, again.text
    assert again.json()["user"]["email"] == email
    # A full session, not the bare access token riders get - the merchant app's
    # existing refresh path depends on this.
    assert again.json()["refresh_token"]


async def test_the_new_token_reaches_merchant_endpoints(client, db):
    """A password sign-in has to mint the merchant audience.

    get_own_vendor requires both the vendor role and the merchant audience, so a
    token missing the second would 403 on every stall endpoint with a message
    about signing in through a different app.
    """
    from app.db.models.user import User
    from app.db.models.vendor import Vendor
    from sqlalchemy import select

    email = _email()
    tokens = await _otp_signin(client, email)
    await client.put(
        "/auth/vendor/password",
        headers=_bearer(tokens["access_token"]),
        json={"password": "a-good-enough-one"},
    )

    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    db.add(Vendor(user_id=user.id, stall_name="Password Stall", is_approved=True, is_open=True))
    await db.commit()

    signed_in = await client.post(
        "/auth/vendor/login", json={"email": email, "password": "a-good-enough-one"}
    )
    mine = await client.get(
        "/vendors/me", headers=_bearer(signed_in.json()["access_token"])
    )
    assert mine.status_code == 200, mine.text
    assert mine.json()["stall_name"] == "Password Stall"


async def test_forgetting_the_password_is_just_the_email_code_again(client):
    """There is no reset flow, and this is why none is needed.

    The way back in is the code they already use, and the set-password route is
    what follows it. Nothing extra to expire, leak or get wrong.
    """
    email = _email()
    first = await _otp_signin(client, email)
    await client.put(
        "/auth/vendor/password",
        headers=_bearer(first["access_token"]),
        json={"password": "the-forgotten-one"},
    )

    # Months later, with no idea what it was.
    back_in = await _otp_signin(client, email)
    reset = await client.put(
        "/auth/vendor/password",
        headers=_bearer(back_in["access_token"]),
        json={"password": "the-replacement"},
    )
    assert reset.status_code == 200

    assert (
        await client.post(
            "/auth/vendor/login", json={"email": email, "password": "the-replacement"}
        )
    ).status_code == 200
    assert (
        await client.post(
            "/auth/vendor/login", json={"email": email, "password": "the-forgotten-one"}
        )
    ).status_code == 401


# --- what a password must not get you ---------------------------------------


async def test_a_wrong_password_and_an_unknown_address_answer_identically(client):
    """Byte for byte, because a stall's address is public on the storefront.

    If a wrong address answered differently from a wrong password, the login
    route would be a free check of which addresses are worth attacking.
    """
    email = _email()
    tokens = await _otp_signin(client, email)
    await client.put(
        "/auth/vendor/password",
        headers=_bearer(tokens["access_token"]),
        json={"password": "the-real-password"},
    )

    wrong_password = await client.post(
        "/auth/vendor/login", json={"email": email, "password": "not-the-real-one"}
    )
    unknown_address = await client.post(
        "/auth/vendor/login",
        json={"email": f"nobody.{uuid.uuid4().hex[:8]}@gmail.com", "password": "anything-at-all"},
    )

    assert wrong_password.status_code == unknown_address.status_code == 401
    assert wrong_password.json() == unknown_address.json()


async def test_an_account_with_no_password_cannot_be_signed_into(client):
    """The table fails closed: no row means no password login, full stop."""
    email = _email()
    await _otp_signin(client, email)

    r = await client.post("/auth/vendor/login", json={"email": email, "password": ""})
    assert r.status_code == 422  # too short to even be a password

    r = await client.post("/auth/vendor/login", json={"email": email, "password": "guessing"})
    assert r.status_code == 401


async def test_a_customer_cannot_sign_in_here_even_with_the_right_password(
    client, db, customer
):
    """A role is not something a login may change.

    Mirrors the admin route, which refuses a non-admin holding the correct admin
    password. Here it matters more: the merchant audience reaches every stall
    endpoint, so a customer who got through would be a stall.
    """
    from app.db.models.merchant_credential import MerchantCredential
    from app.modules.auth.passwords import hash_password

    user, _ = customer
    # Give them a credential row directly - the route that writes one requires
    # the vendor role, so this is building a state the API cannot produce, to
    # prove the login check does not rely on that being true.
    db.add(
        MerchantCredential(user_id=user.id, password_hash=hash_password("perfectly-correct"))
    )
    await db.commit()

    r = await client.post(
        "/auth/vendor/login", json={"email": user.email, "password": "perfectly-correct"}
    )
    assert r.status_code == 401


async def test_a_customer_cannot_set_a_stall_password(client, customer):
    """The write side of the same rule."""
    _, headers = customer
    r = await client.put(
        "/auth/vendor/password", headers=headers, json={"password": "let-me-in-please"}
    )
    assert r.status_code in (401, 403)


async def test_a_short_password_is_refused(client):
    email = _email()
    tokens = await _otp_signin(client, email)
    r = await client.put(
        "/auth/vendor/password",
        headers=_bearer(tokens["access_token"]),
        json={"password": "short"},
    )
    assert r.status_code == 422


# --- what changing a password has to do -------------------------------------


async def test_changing_the_password_signs_the_other_devices_out(client):
    """Otherwise changing it after losing a phone achieves nothing.

    The old session's refresh token is what is actually revoked - an access token
    lives an hour by design and is not revocable - so this checks the thing that
    decides whether the old device gets back in tomorrow.
    """
    email = _email()
    old_device = await _otp_signin(client, email)
    await client.put(
        "/auth/vendor/password",
        headers=_bearer(old_device["access_token"]),
        json={"password": "before-the-change"},
    )

    # The phone that was lost still holds this.
    lost_refresh = (
        await client.post(
            "/auth/vendor/login", json={"email": email, "password": "before-the-change"}
        )
    ).json()["refresh_token"]

    new_device = await _otp_signin(client, email)
    changed = await client.put(
        "/auth/vendor/password",
        headers=_bearer(new_device["access_token"]),
        json={"password": "after-the-change"},
    )
    assert changed.status_code == 200

    stale = await client.post("/auth/refresh", json={"refresh_token": lost_refresh})
    assert stale.status_code == 401

    # And the session handed back by the change itself still works.
    assert (
        await client.post(
            "/auth/refresh", json={"refresh_token": changed.json()["refresh_token"]}
        )
    ).status_code == 200


async def test_the_old_password_stops_working(client):
    email = _email()
    tokens = await _otp_signin(client, email)
    await client.put(
        "/auth/vendor/password",
        headers=_bearer(tokens["access_token"]),
        json={"password": "the-first-one"},
    )

    again = await _otp_signin(client, email)
    await client.put(
        "/auth/vendor/password",
        headers=_bearer(again["access_token"]),
        json={"password": "the-second-one"},
    )

    assert (
        await client.post(
            "/auth/vendor/login", json={"email": email, "password": "the-first-one"}
        )
    ).status_code == 401


async def test_the_email_is_normalised_the_same_way_everywhere(client):
    """Plus-tagging and case must not make a second door.

    normalize_email collapses both, so a stall that signed up as Ravi@gmail.com
    can sign in as ravi@gmail.com - and, more to the point, ravi+1@gmail.com is
    not a separate account with a separate password.
    """
    email = _email()
    tokens = await _otp_signin(client, email)
    await client.put(
        "/auth/vendor/password",
        headers=_bearer(tokens["access_token"]),
        json={"password": "same-account-either-way"},
    )

    local, domain = email.split("@")
    for variant in (email.upper(), f"{local}+phone@{domain}"):
        r = await client.post(
            "/auth/vendor/login", json={"email": variant, "password": "same-account-either-way"}
        )
        assert r.status_code == 200, f"{variant} should be the same account"
