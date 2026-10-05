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

from app.modules.payments import razorpay

# Shared by every id below so one grep finds all of it, in the database as well
# as in the code.
PREFIX = "mock_"

EVENT_TYPE = "mock.payment.captured"


def gateway_order_id_for(order_id: uuid.UUID) -> str:
    """Deliberately not the "order_" shape Razorpay mints.

    A real webhook names a Razorpay order id and is matched by querying
    payments.gateway_order_id, so a mock row could in principle be named by one.
    The prefix is what stops that: no Razorpay id begins with "mock_", and the
    webhook route is closed in mock mode anyway, so this is the second of two
    independent reasons the universes cannot cross.
    """
    return f"{PREFIX}order_{order_id}"


def is_mock(value: str | None) -> bool:
    """Whether an id was minted here. For reading rows back, not for auth."""
    return bool(value) and value.startswith(PREFIX)


def success_entity(*, gateway_order_id: str, amount: Decimal) -> dict:
    """The payment entity Razorpay would have sent for a successful payment.

    An entity rather than a whole webhook body, because apply_payment_success
    takes one: the real webhook and the checkout callback both reduce to this
    shape, and the mock going through the same door is what keeps it honest.

    Built with the amount read from the payments row, so it passes the same
    amount check a real payload does rather than bypassing it. That check is the
    one thing standing between a forged payload and an order marked paid, so it
    must stay on the path even here.
    """
    return {
        # Unique per confirmation, because the payment_events ledger is keyed on
        # it: a fixed value would make the second mock payment of the session
        # look like a duplicate of the first.
        "id": f"{PREFIX}pay_{uuid.uuid4().hex[:16]}",
        "entity": "payment",
        "amount": razorpay.to_paise(amount),
        "currency": "INR",
        "status": "captured",
        "order_id": gateway_order_id,
        "method": "mock",
        "created_at": int(datetime.now(timezone.utc).timestamp()),
    }
