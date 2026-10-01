import uuid

from pydantic import BaseModel


class PaymentSessionOut(BaseModel):
    """Everything the browser needs to open Cashfree's checkout, and nothing more.

    Deliberately carries no amount. The Cashfree SDK takes only the session id,
    so in the happy path there is no figure on the client for anybody to edit -
    sending one anyway would invent the attack surface this avoids.
    """

    payment_session_id: str
    cf_order_id: str
    # "sandbox" or "production", so the SDK opens against the environment this
    # session was actually minted in. Hardcoding it into the bundle is how those
    # two end up disagreeing after a deploy.
    mode: str
    order_id: uuid.UUID


class WebhookAck(BaseModel):
    status: str
