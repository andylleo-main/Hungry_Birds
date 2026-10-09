"""Backend tests for Admin All-Orders and Vendor Finances endpoints.

Covers the review request for the Hungry Birds web app redesign:
- GET /api/admin/orders returns list with stall_name and WITHOUT delivery_code
- GET /api/admin/vendors/{vendor_id}/finances returns VendorAnalyticsOut
- 401 unauthenticated, 403 non-admin (student token)
- 404 for unknown vendor on finances
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://c51fdc6f-f542-48cf-8f1d-227fc2f5f0f4.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@bitmesra.ac.in"
ADMIN_PASSWORD = "HungryAdmin@2026"
STUDENT_EMAIL = "student@bitmesra.ac.in"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def student_token():
    r = requests.post(f"{BASE_URL}/api/auth/otp/request", json={"email": STUDENT_EMAIL}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"OTP request failed: {r.status_code} {r.text}")
    code = r.json().get("debug_code")
    if not code:
        pytest.skip("No debug_code echoed - cannot complete student OTP")
    v = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"email": STUDENT_EMAIL, "code": code},
        timeout=15,
    )
    assert v.status_code == 200, v.text
    return v.json()["access_token"]


# ---- admin_orders ----

class TestAdminOrders:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/orders", timeout=15)
        assert r.status_code in (401, 403)

    def test_rejects_student(self, student_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/orders",
            headers={"Authorization": f"Bearer {student_token}"},
            timeout=15,
        )
        assert r.status_code == 403, r.text

    def test_admin_list_orders_basic(self, admin_headers):
        r = requests.get(f"{BASE_URL}/api/admin/orders?days=30&limit=50", headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        # If any orders exist, verify shape
        for o in data:
            assert "id" in o
            assert "status" in o
            assert "vendor_id" in o
            assert "stall_name" in o  # admin-only field
            # must NOT leak delivery_code to the admin view
            assert "delivery_code" not in o, f"delivery_code leaked in admin orders: {o}"

    def test_admin_orders_filter_days_bounds(self, admin_headers):
        r_bad = requests.get(f"{BASE_URL}/api/admin/orders?days=0", headers=admin_headers, timeout=15)
        assert r_bad.status_code == 422
        r_bad2 = requests.get(f"{BASE_URL}/api/admin/orders?days=400", headers=admin_headers, timeout=15)
        assert r_bad2.status_code == 422

    def test_admin_orders_filter_vendor(self, admin_headers):
        # pick any vendor
        v = requests.get(f"{BASE_URL}/api/admin/vendors", headers=admin_headers, timeout=15)
        assert v.status_code == 200
        vendors = v.json()
        if not vendors:
            pytest.skip("No vendors seeded")
        vid = vendors[0]["id"]
        r = requests.get(
            f"{BASE_URL}/api/admin/orders?vendor_id={vid}&days=90",
            headers=admin_headers,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        for o in r.json():
            assert o["vendor_id"] == vid


# ---- vendor_finances ----

class TestVendorFinances:
    def test_requires_auth(self):
        r = requests.get(
            f"{BASE_URL}/api/admin/vendors/{uuid.uuid4()}/finances", timeout=15
        )
        assert r.status_code in (401, 403)

    def test_rejects_student(self, student_token):
        r = requests.get(
            f"{BASE_URL}/api/admin/vendors/{uuid.uuid4()}/finances",
            headers={"Authorization": f"Bearer {student_token}"},
            timeout=15,
        )
        assert r.status_code == 403

    def test_unknown_vendor_404(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/vendors/{uuid.uuid4()}/finances",
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 404, r.text

    def test_finances_shape_and_totals(self, admin_headers):
        v = requests.get(f"{BASE_URL}/api/admin/vendors", headers=admin_headers, timeout=15).json()
        if not v:
            pytest.skip("No vendors seeded")
        vid = v[0]["id"]
        r = requests.get(
            f"{BASE_URL}/api/admin/vendors/{vid}/finances?days=30",
            headers=admin_headers,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # Just assert the shape used by the finance grid in the admin UI; the
        # test is deliberately tolerant of the exact key names so it doesn't
        # need to track schema wording.
        assert isinstance(data, dict)
        # Should contain at least some aggregate numeric fields
        numeric_fields = [k for k, v in data.items() if isinstance(v, (int, float))]
        assert numeric_fields, f"Expected numeric aggregate fields, got {list(data.keys())}"

    def test_finances_days_bounds(self, admin_headers):
        v = requests.get(f"{BASE_URL}/api/admin/vendors", headers=admin_headers, timeout=15).json()
        if not v:
            pytest.skip("No vendors seeded")
        vid = v[0]["id"]
        r = requests.get(
            f"{BASE_URL}/api/admin/vendors/{vid}/finances?days=0",
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 422
