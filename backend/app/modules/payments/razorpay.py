"""Talking to Razorpay, and checking that Razorpay is who is talking to us.

Kept apart from the order logic so the part that knows about HMACs and gateway
error shapes does not also know what an order is. Replaced the Cashfree client
of the same shape; the README's Payments section records why.

Hand-rolled over httpx rather than Razorpay's own `razorpay` package, which is
built on synchronous `requests` and would block this single-container event loop
on every checkout. The only thing worth lifting from it is the signature
algorithm, which is three lines of hmac.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

# One host for test and live. Which account a call lands in is decided by the key
# prefix (rzp_test_ / rzp_live_), so there is no environment to keep in sync.
BASE_URL = "https://api.razorpay.com/v1"

# Payment calls are on the checkout path, so they cannot hang a worker for long.
_TIMEOUT = httpx.Timeout(10.0)

# Refunds run after the response, where a slow gateway costs nothing visible -
# but Starlette waits for background tasks before closing the connection, so
# this is still bounded.
_REFUND_TIMEOUT = httpx.Timeout(8.0)

# Razorpay requires a QR to stay open at least 15 minutes. 30 gives a rider room
# to find the customer, re-show a screen that locked, and still have it expire
# the same visit.
QR_WINDOW_MINUTES = 30


class RazorpayError(RuntimeError):
    """Razorpay refused or failed.

    Carries the status and Razorpay's own description so a caller can tell the
    difference between "your account cannot do this" and "that payment does not
    exist" without re-parsing the body.
    """

    def __init__(self, message: str, *, status_code: int = 0, description: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.description = description

    @property
    def is_feature_not_enabled(self) -> bool:
        """Whether this is Razorpay saying the product is not on for this account.

        QR Codes is activated on request rather than by default, so a deployment
        can hold perfectly good credentials and still be unable to mint one. That
        is a message for the rider ("take cash instead"), not a 500, and the only
        way to tell is to read what Razorpay said.
        """
        text = self.description.lower()
        return any(
            phrase in text
            for phrase in ("not enabled", "not activated", "no access", "not allowed to")
        )


def _auth(settings: Settings) -> tuple[str, str]:
    """HTTP Basic, which is how Razorpay authenticates every API call."""
    return (settings.razorpay_key_id, settings.razorpay_key_secret)


def _describe(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    error = payload.get("error") or {}
    return str(error.get("description") or error.get("reason") or payload)[:200]


def _raise_for(response: httpx.Response, what: str) -> None:
    if response.status_code >= 300:
        description = _describe(response)
        raise RazorpayError(
            f"{what} failed ({response.status_code}): {description}",
            status_code=response.status_code,
            description=description,
        )


def to_paise(amount: Decimal) -> int:
    """Rupees to the integer paise every Razorpay amount field expects.

    The quantize is not decoration. `total_amount` is Numeric(10, 2) and arrives
    as a Decimal; multiplying and truncating would turn a half-paise rounding
    artefact into a customer charged a paisa less than the stall was told, and
    the webhook's amount check would then reject their own payment.
    """
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_paise(paise: int) -> Decimal:
    """Back to rupees, for comparing against a column or showing a human."""
    return (Decimal(paise) / 100).quantize(Decimal("0.01"))


async def create_order(
    *,
    receipt: str,
    amount: Decimal,
    notes: dict[str, str],
    settings: Settings,
) -> dict:
    """Open a Razorpay order and return its response.

    The amount comes from the order row, never from the browser.

    Unlike Cashfree, **Razorpay mints the order id**; we cannot choose it. So the
    id it returns is stored on the payment row and every webhook is matched back
    by querying that column, rather than by parsing a prefix out of an id we
    picked. `notes` carries our own ids so a human reading Razorpay's dashboard
    can find the order without that mapping.
    """
    body = {
        "amount": to_paise(amount),
        "currency": "INR",
        # Razorpay caps this at 40 characters. order_number is 11 and is the
        # number a student reads out on the phone, which makes a support call
        # answerable from either side.
        "receipt": receipt[:40],
        "notes": notes,
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(f"{BASE_URL}/orders", auth=_auth(settings), json=body)
    _raise_for(response, "create_order")
    return response.json()


async def fetch_payment(payment_id: str, settings: Settings) -> dict:
    """What Razorpay thinks the state of one payment is.

    Used by the checkout callback. The browser's handback is signed, which proves
    Razorpay issued that payment id against that order, but it says nothing about
    the amount or whether the money was actually captured - so those two are read
    from here rather than believed from a page the customer controls.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(f"{BASE_URL}/payments/{payment_id}", auth=_auth(settings))
    _raise_for(response, "fetch_payment")
    return response.json()


async def order_payments(gateway_order_id: str, settings: Settings) -> list[dict]:
    """Every payment attempted against one order.

    The way back when a refund is due but no webhook ever landed, so we hold no
    payment id to refund against.
    """
    async with httpx.AsyncClient(timeout=_REFUND_TIMEOUT) as client:
        response = await client.get(
            f"{BASE_URL}/orders/{gateway_order_id}/payments", auth=_auth(settings)
        )
    _raise_for(response, "order_payments")
    return list(response.json().get("items") or [])


async def list_refunds(payment_id: str, settings: Settings) -> list[dict]:
    """Refunds that already exist against a payment.

    Called before creating one, every time. See `refund` for why.
    """
    async with httpx.AsyncClient(timeout=_REFUND_TIMEOUT) as client:
        response = await client.get(
            f"{BASE_URL}/payments/{payment_id}/refunds", auth=_auth(settings)
        )
    _raise_for(response, "list_refunds")
    return list(response.json().get("items") or [])


async def refund(
    *,
    payment_id: str,
    amount: Decimal,
    notes: dict[str, str],
    settings: Settings,
) -> dict:
    """Refund a payment in full.

    **Razorpay has no client-chosen idempotency key for refunds.** Cashfree did,
    and the retry drain relied on it: the same `refund_id` on every attempt meant
    a retry could never pay out twice. Here the id comes back from Razorpay, so
    a drain that simply retried would create a second refund and send a customer
    their money twice.

    So the caller must check `list_refunds` first and adopt what is already
    there. This function is the unconditional half and does exactly what it is
    told; `service.attempt_refund` is where the guard lives.
    """
    async with httpx.AsyncClient(timeout=_REFUND_TIMEOUT) as client:
        response = await client.post(
            f"{BASE_URL}/payments/{payment_id}/refund",
            auth=_auth(settings),
            json={"amount": to_paise(amount), "speed": "normal", "notes": notes},
        )
    _raise_for(response, "refund")
    return response.json()


async def create_upi_qr(
    *,
    amount: Decimal,
    description: str,
    notes: dict[str, str],
    settings: Settings,
) -> dict:
    """A single-use, fixed-amount UPI QR for one order.

    This is the dynamic QR a rider holds up, not a printed sticker: `single_use`
    closes it the moment one payment lands, `fixed_amount` with `payment_amount`
    locks it to this order's total so nobody can underpay, and `close_by` expires
    it. Razorpay then tells us it was paid through the `qr_code.credited` webhook,
    which is the point of routing this through a gateway at all - the rider never
    has to be believed about whether the money arrived.

    QR Codes is an on-request product on a Razorpay account. If it is not on,
    this raises with `is_feature_not_enabled` set and the rider is told to take
    cash.
    """
    close_by = datetime.now(timezone.utc) + timedelta(minutes=QR_WINDOW_MINUTES)

    body = {
        "type": "upi_qr",
        "name": "Hungry Birds",
        "usage": "single_use",
        "fixed_amount": True,
        "payment_amount": to_paise(amount),
        "description": description[:2048],
        # Razorpay requires at least 15 minutes out and rejects anything sooner.
        "close_by": int(close_by.timestamp()),
        "notes": notes,
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f"{BASE_URL}/payments/qr_codes", auth=_auth(settings), json=body
        )
    _raise_for(response, "create_upi_qr")
    return response.json()


async def close_upi_qr(qr_id: str, settings: Settings) -> None:
    """Shut a QR that is no longer collectable.

    Best effort. A single-use QR closes itself once paid and expires on its own at
    `close_by`, so failing to close one leaves a code that can take money for an
    order somebody already settled - worth attempting, not worth failing a
    request over.
    """
    try:
        async with httpx.AsyncClient(timeout=_REFUND_TIMEOUT) as client:
            response = await client.post(
                f"{BASE_URL}/payments/qr_codes/{qr_id}/close", auth=_auth(settings)
            )
        if response.status_code >= 300:
            logger.warning("could not close qr %s: %s", qr_id, _describe(response))
    except httpx.HTTPError as exc:
        logger.warning("could not close qr %s: %s", qr_id, exc)


def verify_webhook(*, raw_body: bytes, signature: str, settings: Settings) -> bool:
    """Check that a webhook really came from Razorpay.

    HMAC-SHA256 over the *raw* body, hex, keyed with the webhook signing secret.
    The raw bytes matter: re-serialising a parsed payload changes key order and
    whitespace, so the signature would never match - which is the most common way
    HMAC webhook verification is quietly broken, because it fails closed and looks
    like a configuration problem.

    Two things differ from the Cashfree client this replaces. The key is the
    webhook secret, **not** the API key secret - mixing those two up is the other
    common failure, and they are different settings here for that reason. And
    Razorpay sends no timestamp, so there is no staleness window to check:
    replay protection rests entirely on the unique index over
    `payment_events.event_id`, which the route fills from X-Razorpay-Event-Id.
    """
    if not settings.razorpay_webhook_secret or not signature:
        return False

    expected = hmac.new(
        settings.razorpay_webhook_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_checkout_signature(
    *, gateway_order_id: str, payment_id: str, signature: str, settings: Settings
) -> bool:
    """Check the handback Checkout gives the browser when a payment succeeds.

    A different signature from the webhook one above, over `order_id|payment_id`
    and keyed with the **API key secret**. Both are HMAC-SHA256 and they are easy
    to confuse; using the webhook secret here fails every valid payment, and
    using the key secret on a webhook accepts none.
    """
    if not settings.razorpay_key_secret or not signature:
        return False

    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{gateway_order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_body(raw_body: bytes) -> dict:
    """Parse a webhook body with any decimal as Decimal, never float.

    Razorpay sends money as integer paise, so this is belt and braces rather than
    load-bearing as it was for Cashfree - but a float creeping into an amount
    comparison is the kind of bug that only shows up on the rupee values that do
    not round-trip through binary floating point, which is a terrible way to find
    out.
    """
    return json.loads(raw_body, parse_float=Decimal)
