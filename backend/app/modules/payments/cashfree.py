"""Talking to Cashfree, and checking that Cashfree is who is talking to us.

Kept apart from the order logic so the part that knows about HMACs and gateway
error shapes does not also know what an order is.
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Payment calls are on the checkout path, so they cannot hang a worker for long.
_TIMEOUT = httpx.Timeout(10.0)

# Refunds run after the response, where a slow gateway costs nothing visible -
# but Starlette waits for background tasks before closing the connection, so
# this is still bounded.
_REFUND_TIMEOUT = httpx.Timeout(8.0)


class CashfreeError(RuntimeError):
    """Cashfree refused or failed. Carries its message for the log."""


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "x-api-version": settings.cashfree_api_version,
        "x-client-id": settings.cashfree_app_id,
        "x-client-secret": settings.cashfree_secret_key,
        "Content-Type": "application/json",
    }


def _message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    return str(payload.get("message") or payload)[:200]


async def create_order(
    *,
    cf_order_id: str,
    amount: Decimal,
    customer_id: str,
    customer_name: str | None,
    customer_email: str,
    customer_phone: str,
    settings: Settings,
) -> dict:
    """Open a payment order and return Cashfree's response.

    The amount comes from the order row, never from the browser: the client is
    handed only a session id, and the Cashfree SDK takes nothing else, so in the
    happy path there is literally no number for a customer to tamper with.
    """
    expiry = datetime.now(timezone.utc) + timedelta(minutes=settings.cashfree_order_expiry_minutes)

    body = {
        "order_id": cf_order_id,
        # str() rather than float(): the column is Numeric(10, 2) and binary
        # floating point cannot represent every two-decimal rupee value exactly.
        "order_amount": str(amount),
        "order_currency": "INR",
        "customer_details": {
            "customer_id": customer_id,
            "customer_name": customer_name or "Hungry Birds customer",
            "customer_email": customer_email,
            "customer_phone": customer_phone,
        },
        "order_meta": {
            "return_url": f"{settings.public_base_url}/orders/{cf_order_id.removeprefix('hb_')}",
            "notify_url": f"{settings.public_base_url}/api/payments/cashfree/webhook",
        },
        # Closes the window at the gateway, which is what actually stops a
        # customer paying for an abandoned order hours later. Our own sweep is
        # only bookkeeping on top of this.
        "order_expiry_time": expiry.isoformat(timespec="seconds"),
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            f"{settings.cashfree_base_url}/orders", headers=_headers(settings), json=body
        )
    if response.status_code >= 300:
        raise CashfreeError(f"create_order failed ({response.status_code}): {_message(response)}")
    return response.json()


async def refund(
    *,
    cf_order_id: str,
    refund_id: str,
    amount: Decimal,
    note: str,
    settings: Settings,
) -> dict:
    """Refund an order in full.

    `refund_id` is generated once per order and reused on every attempt, because
    Cashfree treats it as the idempotency key - a fresh id per retry is precisely
    how a customer ends up refunded twice.
    """
    async with httpx.AsyncClient(timeout=_REFUND_TIMEOUT) as client:
        response = await client.post(
            f"{settings.cashfree_base_url}/orders/{cf_order_id}/refunds",
            headers=_headers(settings),
            json={
                "refund_amount": str(amount),
                "refund_id": refund_id,
                "refund_note": note[:100],
            },
        )

    # A refund that already exists is success, not failure: it means an earlier
    # attempt got through and we are retrying something already done.
    if response.status_code == 409:
        return {"refund_status": "PENDING", "already_requested": True}
    if response.status_code >= 300:
        raise CashfreeError(f"refund failed ({response.status_code}): {_message(response)}")
    return response.json()


async def fetch_order(cf_order_id: str, settings: Settings) -> dict:
    """Ask Cashfree what it thinks the state of an order is.

    The fallback for a webhook that never arrives. Webhooks are the normal path,
    but they are somebody else's delivery guarantee, and an order that is paid
    while the stall sees nothing is the worst failure this system has.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(
            f"{settings.cashfree_base_url}/orders/{cf_order_id}", headers=_headers(settings)
        )
    if response.status_code >= 300:
        raise CashfreeError(f"fetch_order failed ({response.status_code}): {_message(response)}")
    return response.json()


def verify_webhook(
    *, raw_body: bytes, timestamp: str, signature: str, settings: Settings
) -> bool:
    """Check that a webhook really came from Cashfree, and is not a replay.

    Signed over the timestamp concatenated with the *raw* body. The raw bytes
    matter: re-serialising a parsed payload changes key order and whitespace, so
    the signature would never match - which is the single most common way HMAC
    webhook verification is quietly broken, because it fails closed and looks
    like a configuration problem.
    """
    if not settings.cashfree_secret_key or not timestamp or not signature:
        return False

    try:
        age = abs(time.time() - int(timestamp))
    except (TypeError, ValueError):
        return False
    if age > settings.cashfree_webhook_tolerance_seconds:
        # A valid signature on a stale body is a captured request being replayed.
        logger.warning("rejected a cashfree webhook that was %.0fs old", age)
        return False

    digest = hmac.new(
        settings.cashfree_secret_key.encode(),
        timestamp.encode() + raw_body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


def parse_body(raw_body: bytes) -> dict:
    """Parse a webhook body with money as Decimal, never float.

    `order_amount` arrives as a JSON number. Plain json.loads makes it a float,
    and Decimal("129.00") != 129.0, so the amount check below would reject every
    payment - or, worse, only some of them, depending on which rupee values
    happen to round-trip through binary floating point.
    """
    return json.loads(raw_body, parse_float=Decimal)
