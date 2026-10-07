"""The headers a browser has to be told about, on every response.

Cheap to add and easy to lose: nothing in the app fails when they go missing, so
only a test notices. The CSP is the one with teeth and the one shipped
report-only, because a policy guessed slightly wrong does not degrade - it stops
people paying.
"""

import pytest

pytest.importorskip("httpx")


async def test_the_api_carries_them(client):
    r = await client.get("/health")

    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "content-security-policy-report-only" in r.headers


async def test_the_csp_is_report_only_for_now(client):
    """Enforcing a policy that has not been watched against a real Razorpay
    checkout is how you find out it was wrong from somebody who could not pay."""
    r = await client.get("/health")

    assert "content-security-policy" not in r.headers
    assert "content-security-policy-report-only" in r.headers


async def test_the_csp_lets_checkout_and_the_fonts_through(client):
    """The three origins index.html and lib/razorpay.ts actually reach for. A
    policy that forgets one of these is a policy that breaks the app the moment
    it stops being report-only."""
    csp = (await client.get("/health")).headers["content-security-policy-report-only"]

    assert "https://checkout.razorpay.com" in csp
    assert "https://fonts.googleapis.com" in csp
    assert "https://fonts.gstatic.com" in csp
    assert "https://res.cloudinary.com" in csp


async def test_nothing_may_frame_this(client):
    """Said twice on purpose: frame-ancestors is the one browsers read now,
    X-Frame-Options the one older ones do. The admin panel is the page that
    would be worth framing."""
    r = await client.get("/health")

    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy-report-only"]


async def test_a_refused_request_still_carries_them(client):
    """A 404 renders in a browser like any other response. The middleware is
    outermost so that an early refusal from the rate limiter or the body-size
    check is covered too."""
    r = await client.get("/api/orders/not-a-uuid")

    assert r.status_code >= 400
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_hsts_is_off_in_development(client):
    """On localhost a browser pins the whole origin to HTTPS and keeps the pin
    long after the setting changes - it is cached there, not here. The test
    suite runs as development, which is why this asserts the absence."""
    r = await client.get("/health")

    assert "strict-transport-security" not in r.headers
