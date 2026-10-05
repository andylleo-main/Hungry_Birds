import uuid

from pydantic import BaseModel


class PaymentSessionOut(BaseModel):
    """Everything the browser needs to open Razorpay Checkout, and nothing more.

    Unlike the Cashfree session this replaces, it carries an amount - Razorpay
    Checkout needs one. That is not a new attack surface: the figure comes off
    the payments row, the gateway order it names was opened for exactly that
    figure, and Razorpay charges what *it* has on the order rather than what the
    page asks for. A tampered amount here changes the label on the sheet and
    nothing about the money.
    """

    # Razorpay's order id. We do not choose it, which is why the webhook matches
    # on a column rather than on a prefix we invented.
    gateway_order_id: str
    # Razorpay's publishable half. Meant to reach the browser; the key secret and
    # the webhook secret never leave the server.
    key_id: str
    # Integer paise, which is the only unit Razorpay states money in.
    amount: int
    currency: str
    # "razorpay" or "mock". The browser skips Checkout entirely on "mock" and
    # calls the confirm route instead, and the checkout page shows a banner for
    # it, so a tester is never left guessing whether a payment was real.
    mode: str
    order_id: uuid.UUID


class PaymentCallback(BaseModel):
    """What Razorpay Checkout hands back to the page on a successful payment.

    Believed only as far as its signature goes - that it was issued by Razorpay
    for this order. The amount and whether the money was actually captured are
    read from the API afterwards, never from here.
    """

    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class WebhookAck(BaseModel):
    status: str
