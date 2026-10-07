"""Who may sign in where, and what a token from one app may do in another.

Three clients now share one API with three different rules about who may hold an
account. The rules that actually bite are checked here: a stall account cannot
spend money on campus, ordering is institute-only at the point of ordering, and
a session belonging to one app cannot be replayed against another's endpoints.
"""

import uuid

import pytest

pytest.importorskip("httpx")


def _lines(item):
    return [{"menu_item_id": str(item.id), "quantity": 1}]


async def _otp_login(client, path_prefix, email):
    """Run the OTP dance, returning the token response, or skip if codes are hidden."""
    r = await client.post(f"{path_prefix}/otp/request", json={"email": email})
    if r.status_code != 200:
        return r
    code = r.json().get("debug_code")
    if not code:
        pytest.skip("needs OTP_DEBUG_ECHO to read the code back")
    return await client.post(f"{path_prefix}/otp/verify", json={"email": email, "code": code})


# --- the rule that keeps ordering on campus ---------------------------------


async def test_a_stall_account_cannot_place_an_order(client, vendor, menu_item):
    """The gate that lets stalls use any email address without opening ordering.

    Before this, any signed-in account could order; that was safe only because
    every account had had to prove an institute address to exist at all.
    """
    v, headers = vendor
    r = await client.post(
        "/orders", headers=headers, json={"vendor_id": str(v.id), "items": _lines(menu_item)}
    )
    assert r.status_code == 403


async def test_a_customer_with_an_outside_address_cannot_order(
    client, db, vendor, menu_item
):
    """Belt and braces: the domain is re-checked where the money is spent.

    A customer can only be created through the institute-only route today, so
    this account should not exist. The check is what makes the campus
    restriction a property of this endpoint rather than an accident of how
    accounts happen to be made.
    """
    from app.core.security import TokenAudience, create_access_token
    from app.db.models.user import User, UserRole

    outsider = User(
        email=f"outsider.{uuid.uuid4().hex[:8]}@gmail.com",
        role=UserRole.CUSTOMER,
        phone="+919876500000",
    )
    db.add(outsider)
    await db.commit()
    await db.refresh(outsider)

    headers = {
        "Authorization": f"Bearer {create_access_token(str(outsider.id), TokenAudience.WEB)}"
    }
    v, _ = vendor
    r = await client.post(
        "/orders", headers=headers, json={"vendor_id": str(v.id), "items": _lines(menu_item)}
    )
    assert r.status_code == 400
    assert "place an order" in r.json()["detail"]


# --- token audience ---------------------------------------------------------


async def test_a_web_token_cannot_reach_vendor_endpoints(client, db, vendor):
    """The stall's own owner, holding a web-app token, is refused."""
    from app.core.security import TokenAudience, create_access_token
    from app.db.models.vendor import Vendor

    v, _ = vendor
    owner_id = (await db.get(Vendor, v.id)).user_id
    web = {"Authorization": f"Bearer {create_access_token(str(owner_id), TokenAudience.WEB)}"}

    r = await client.get("/vendors/me", headers=web)
    assert r.status_code == 403
    assert "different Hungry Birds app" in r.json()["detail"]


async def test_a_token_from_before_audiences_asks_for_a_fresh_sign_in(client, db, vendor):
    """401, not 403, so a client refreshes and retries instead of dead-ending."""
    import jwt

    from app.core.config import get_settings
    from app.db.models.vendor import Vendor

    v, _ = vendor
    owner_id = (await db.get(Vendor, v.id)).user_id
    settings = get_settings()
    legacy = jwt.encode(
        {"sub": str(owner_id), "type": "access"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    r = await client.get("/vendors/me", headers={"Authorization": f"Bearer {legacy}"})
    assert r.status_code == 401
    assert "sign in again" in r.json()["detail"].lower()


async def test_a_merchant_token_still_works_on_vendor_endpoints(client, vendor):
    v, headers = vendor
    r = await client.get("/vendors/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == str(v.id)


# --- signing up -------------------------------------------------------------


async def test_a_stall_may_sign_up_with_any_address(client):
    email = f"stall.{uuid.uuid4().hex[:8]}@gmail.com"
    r = await _otp_login(client, "/auth/vendor", email)
    assert r.status_code == 200, r.text
    body = r.json()
    # The role is settled at creation, not by a later request.
    assert body["user"]["role"] == "vendor"
    assert body["user"]["email"] == email


async def test_a_customer_still_needs_an_institute_address(client):
    r = await client.post(
        "/auth/otp/request", json={"email": f"nope.{uuid.uuid4().hex[:8]}@gmail.com"}
    )
    assert r.status_code == 400
    assert "sign up" in r.json()["detail"]


async def test_an_address_that_is_already_a_customer_cannot_become_a_stall(
    client, customer
):
    """Refused rather than converted, because role must not be mutable."""
    user, _ = customer
    r = await _otp_login(client, "/auth/vendor", user.email)
    assert r.status_code == 400
    assert "different address for your stall" in r.json()["detail"]


async def test_applying_no_longer_promotes_a_customer_account(client, customer):
    """The old hole: a student could turn their own account into a stall."""
    user, headers = customer
    r = await client.post(
        "/vendors/apply", headers=headers, json={"stall_name": "Sneaky Samosas"}
    )
    assert r.status_code == 403


async def test_a_vendor_signed_up_this_way_can_describe_their_stall(client):
    email = f"stall.{uuid.uuid4().hex[:8]}@outlook.com"
    r = await _otp_login(client, "/auth/vendor", email)
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = await client.post("/vendors/apply", headers=headers, json={"stall_name": "Chai Point"})
    assert r.status_code == 201, r.text
    assert r.json()["stall_name"] == "Chai Point"
    # Not sellable until an admin says so.
    assert r.json()["is_approved"] is False
    # And every location is on from the start.
    assert r.json()["delivery_enabled"] is True


# --- refresh ----------------------------------------------------------------


async def test_refreshing_keeps_a_session_on_its_own_app(client):
    """A merchant session must not refresh into a token that also works on web."""
    email = f"stall.{uuid.uuid4().hex[:8]}@gmail.com"
    r = await _otp_login(client, "/auth/vendor", email)
    assert r.status_code == 200, r.text

    r = await client.post("/auth/refresh", json={"refresh_token": r.json()["refresh_token"]})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # Still a merchant token: reaches vendor endpoints (404 - no stall yet - not 403).
    r = await client.get("/vendors/me", headers=headers)
    assert r.status_code == 404


# --- upload permits ---------------------------------------------------------


async def test_a_customer_cannot_get_a_cloudinary_upload_permit(client, customer):
    """Each one is a signed permit to write to our media account."""
    user, headers = customer
    r = await client.get("/media/signature", headers=headers)
    assert r.status_code == 403


async def test_an_unapproved_stall_cannot_get_an_upload_permit(client, db):
    """The gate used to be "signed up and pressed Apply", which is two requests
    away from a stranger with any inbox - the merchant sign-in takes any email
    address on the internet, because a stall owner has no institute one. That
    made a permit to spend our Cloudinary quota available to anybody who wanted
    one. Approval is the first point at which a human has looked.
    """
    import uuid as _uuid

    from app.core.security import TokenAudience
    from app.db.models.user import User, UserRole
    from app.db.models.vendor import Vendor

    from tests.conftest import _token

    owner = User(email=f"new.{_uuid.uuid4().hex[:8]}@example.com", role=UserRole.VENDOR)
    db.add(owner)
    await db.commit()
    await db.refresh(owner)
    db.add(Vendor(user_id=owner.id, stall_name="Waiting Room", is_approved=False))
    await db.commit()

    headers = _token(owner.id, TokenAudience.MERCHANT)
    r = await client.get("/media/signature", headers=headers)

    assert r.status_code == 403
    assert "approval" in r.json()["detail"]


async def test_an_approved_stall_still_gets_one(client, vendor):
    """The other half: the gate must not have closed on the stalls it is for.

    Cloudinary has to be configured for this route to answer at all, and the
    suite's settings leave it blank - so this one names credentials the same way
    `cashback_on` names rates.
    """
    from app.core.config import get_settings
    from app.main import app
    from tests.conftest import _test_settings

    configured = _test_settings().model_copy(
        update={
            "cloudinary_cloud_name": "test-cloud",
            "cloudinary_api_key": "test-key",
            "cloudinary_api_secret": "test-secret",
        }
    )
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        _, headers = vendor
        r = await client.get("/media/signature", headers=headers)
    finally:
        app.dependency_overrides[get_settings] = lambda: _test_settings()

    assert r.status_code == 200, r.text
    assert r.json()["signature"]


async def test_an_unapproved_stall_can_still_build_its_menu(client, db):
    """Approval gates money and other people's resources, not a stall's own
    preparation. Somebody waiting on an admin has to be able to do the work the
    approval is *for*, or the queue becomes a dead end."""
    import uuid as _uuid

    from app.core.security import TokenAudience
    from app.db.models.user import User, UserRole
    from app.db.models.vendor import Vendor

    from tests.conftest import _token

    owner = User(email=f"prep.{_uuid.uuid4().hex[:8]}@example.com", role=UserRole.VENDOR)
    db.add(owner)
    await db.commit()
    await db.refresh(owner)
    db.add(Vendor(user_id=owner.id, stall_name="Prepping", is_approved=False))
    await db.commit()

    headers = _token(owner.id, TokenAudience.MERCHANT)
    r = await client.post(
        "/vendors/me/items",
        headers=headers,
        json={"name": "Thali", "price": "120.00"},
    )

    assert r.status_code == 201, r.text
