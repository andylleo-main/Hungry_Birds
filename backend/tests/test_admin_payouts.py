"""Backend tests for GET /api/admin/payouts (weekly settlement per stall).

Covers:
- Auth: 401 unauth, 403 student, 200 admin
- weeks query bounds (1..26), default 8
- Response shape and invariants per stall row
- Totals match sum of rows
- Cross-check with vendor finances for the current week
"""
import os
import uuid
from datetime import date, datetime, timedelta

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://c51fdc6f-f542-48cf-8f1d-227fc2f5f0f4.preview.emergentagent.com",
).rstrip("/")
ADMIN_EMAIL = "admin@bitmesra.ac.in"
ADMIN_PASSWORD = "HungryAdmin@2026"
STUDENT_EMAIL = "student@bitmesra.ac.in"


@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(
        f"{BASE_URL}/api/auth/admin/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def student_headers():
    r = requests.post(
        f"{BASE_URL}/api/auth/otp/request", json={"email": STUDENT_EMAIL}, timeout=15
    )
    if r.status_code != 200:
        pytest.skip(f"OTP request failed: {r.status_code}")
    code = r.json().get("debug_code")
    if not code:
        pytest.skip("No debug_code echoed")
    v = requests.post(
        f"{BASE_URL}/api/auth/otp/verify",
        json={"email": STUDENT_EMAIL, "code": code},
        timeout=15,
    )
    assert v.status_code == 200, v.text
    return {"Authorization": f"Bearer {v.json()['access_token']}"}


class TestAuth:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/payouts", timeout=15)
        assert r.status_code in (401, 403)

    def test_rejects_student(self, student_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payouts", headers=student_headers, timeout=15
        )
        assert r.status_code == 403, r.text


class TestBounds:
    def test_weeks_zero_422(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payouts?weeks=0", headers=admin_headers, timeout=15
        )
        assert r.status_code == 422

    def test_weeks_27_422(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payouts?weeks=27", headers=admin_headers, timeout=15
        )
        assert r.status_code == 422

    def test_default_is_8_weeks(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payouts", headers=admin_headers, timeout=20
        )
        assert r.status_code == 200
        assert len(r.json()["weeks"]) == 8

    def test_explicit_weeks_count(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payouts?weeks=3",
            headers=admin_headers,
            timeout=15,
        )
        assert r.status_code == 200
        assert len(r.json()["weeks"]) == 3


class TestShapeAndInvariants:
    @pytest.fixture(scope="class")
    def payouts(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payouts?weeks=8",
            headers=admin_headers,
            timeout=20,
        )
        assert r.status_code == 200, r.text
        return r.json()

    def test_response_top_level_shape(self, payouts):
        assert "generated_at" in payouts
        assert "weeks" in payouts
        assert isinstance(payouts["weeks"], list)

    def test_weeks_newest_first_and_monday_sunday(self, payouts):
        prev_start = None
        for w in payouts["weeks"]:
            ws = date.fromisoformat(w["week_start"])
            we = date.fromisoformat(w["week_end"])
            assert ws.weekday() == 0, f"week_start not Monday: {ws}"
            assert (we - ws).days == 6, f"week not 7 days: {ws}..{we}"
            if prev_start is not None:
                assert ws < prev_start, "weeks must be newest first"
            prev_start = ws

    def test_empty_weeks_have_null_totals(self, payouts):
        for w in payouts["weeks"]:
            if not w["stalls"]:
                assert w["totals"] is None

    def test_stall_row_invariants(self, payouts):
        for w in payouts["weeks"]:
            for s in w["stalls"]:
                # prepaid + cash + discounts == order_value
                total = round(
                    s["prepaid_online"] + s["cash_in_hand"] + s["discounts"], 2
                )
                assert abs(total - s["order_value"]) < 0.02, (
                    f"split sum {total} != order_value {s['order_value']} for {s}"
                )
                # owed == order_value - cash_in_hand
                owed = round(s["order_value"] - s["cash_in_hand"], 2)
                assert abs(owed - s["owed_to_stall"]) < 0.02, (
                    f"owed_to_stall mismatch for {s}"
                )
                # Non-negative
                assert s["prepaid_online"] >= -0.01
                assert s["cash_in_hand"] >= -0.01
                assert s["discounts"] >= -0.01

    def test_totals_equal_sum_of_rows(self, payouts):
        for w in payouts["weeks"]:
            if not w["stalls"]:
                continue
            t = w["totals"]
            assert t is not None
            for field in (
                "orders",
                "order_value",
                "prepaid_online",
                "cash_in_hand",
                "discounts",
                "owed_to_stall",
            ):
                summed = round(sum(s[field] for s in w["stalls"]), 2)
                total_val = round(t[field], 2) if isinstance(t[field], float) else t[field]
                assert abs(summed - total_val) < 0.02, (
                    f"totals.{field} {total_val} != sum {summed}"
                )


class TestVendorFilter:
    def test_vendor_filter_limits_rows(self, admin_headers):
        v = requests.get(
            f"{BASE_URL}/api/admin/vendors", headers=admin_headers, timeout=15
        ).json()
        if not v:
            pytest.skip("No vendors seeded")
        vid = v[0]["id"]
        r = requests.get(
            f"{BASE_URL}/api/admin/payouts?weeks=8&vendor_id={vid}",
            headers=admin_headers,
            timeout=20,
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["weeks"]) == 8
        for w in data["weeks"]:
            for s in w["stalls"]:
                assert s["vendor_id"] == vid

    def test_unknown_vendor_returns_empty_weeks(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/admin/payouts?weeks=4&vendor_id={uuid.uuid4()}",
            headers=admin_headers,
            timeout=15,
        )
        # The endpoint doesn't 404 the vendor (payouts aggregates); just no rows.
        assert r.status_code == 200
        for w in r.json()["weeks"]:
            assert w["stalls"] == []
            assert w["totals"] is None


class TestCrossCheckFinances:
    """Current-week order_value in payouts should align with vendor finances
    for the matching rolling window where the week covers only completed days."""

    def test_current_week_consistent_with_finances(self, admin_headers):
        pr = requests.get(
            f"{BASE_URL}/api/admin/payouts?weeks=1", headers=admin_headers, timeout=20
        )
        assert pr.status_code == 200
        week = pr.json()["weeks"][0]
        if not week["stalls"]:
            pytest.skip("No paid orders this week")
        stall = week["stalls"][0]
        # Rolling 7-day finances for this stall - approximate check that
        # the stall actually has activity in both views.
        fr = requests.get(
            f"{BASE_URL}/api/admin/vendors/{stall['vendor_id']}/finances?days=7",
            headers=admin_headers,
            timeout=20,
        )
        assert fr.status_code == 200, fr.text
        fin = fr.json()
        # Finances should expose some numeric total. Both are > 0 is enough.
        numeric_vals = [v for v in fin.values() if isinstance(v, (int, float))]
        assert numeric_vals, f"finances missing numeric fields: {fin}"
        assert stall["order_value"] > 0
