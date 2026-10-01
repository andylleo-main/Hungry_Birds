"""A payment gateway that always says yes.

Exists so everything downstream of a payment - the stall's queue, the push, the
rider assignment, the handover code - can be exercised before real Cashfree
credentials exist. It is not a stub that short-circuits the pipeline: it builds
the same webhook payload Cashfree would send and hands it to the same
apply_payment_success, so what gets tested is the real settlement path with a
synthetic trigger.

Three properties keep this from becoming free food in production:

  - It is reachable only when PAYMENTS_MODE=mock, which has no default and is
    never inferred. The app logs a warning on every boot while it is set.
  - Every id it mints is prefixed "mock_". order_id_from_cf only strips "hb_",
    so a real Cashfree webhook can never resolve to a mock payment row, and a
    mock row can never be settled by the real gateway.
  - Each confirmation writes a PaymentEvent of type MOCK_PAYMENT_SUCCESS. Orders
    that were never really paid for stay identifiable forever, which is what
    makes the switch to real payments auditable rather than a guess.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

# Shared by every id below so one grep finds all of it, in the database as well
# as in the code.
PREFIX = "mock_"

EVENT_TYPE = "MOCK_PAYMENT_SUCCESS"


def cf_order_id_for(order_id: uuid.UUID) -> str:
    """Deliberately not the "hb_" shape the real gateway uses.

    service.order_id_from_cf removes "hb_" and nothing else, so this id cannot be
    named by an inbound Cashfree webhook to settle anything.
    """
    return f"{PREFIX}order_{order_id}"


def payment_session_id_for(order_id: uuid.UUID) -> str:
    """Stands in for Cashfree's session id.

    The browser never sends it anywhere - the web app sees mode "mock" and skips
    the SDK entirely - but the column is what marks a payment as ready to be
    attempted, and the checkout route refuses an empty one.
    """
    return f"{PREFIX}session_{order_id}"


def is_mock(value: str | None) -> bool:
    """Whether an id was minted here. For reading rows back, not for auth."""
    return bool(value) and value.startswith(PREFIX)


def success_payload(*, cf_order_id: str, amount: Decimal) -> dict:
    """The webhook body Cashfree would have posted for a successful payment.

    Built with the amount read from the payments row, so it passes the same
    amount check a real payload does rather than bypassing it. That check is the
    one thing standing between a forged payload and an order marked paid, so it
    must stay on the path even here.
    """
    now = datetime.now(timezone.utc).isoformat()
    return {
        "type": EVENT_TYPE,
        "data": {
            "order": {
                "order_id": cf_order_id,
                "order_amount": str(amount),
                "order_currency": "INR",
            },
            "payment": {
                # Unique per confirmation, because the payment_events ledger is
                # keyed on it: a fixed value would make the second mock payment
                # of the session look like a duplicate of the first.
                "cf_payment_id": f"{PREFIX}{uuid.uuid4().hex[:16]}",
                "payment_amount": str(amount),
                "payment_currency": "INR",
                "payment_status": "SUCCESS",
                "payment_time": now,
                "payment_group": "mock",
            },
        },
        "event_time": now,
    }
