"""Taking the money at the door, for whoever is standing there.

A rider and a self-delivering stall owner do the same job on the same order, so
the rules live here rather than in either router: what may be collected, how
cash is recorded, how a QR is minted and retired, and the one guard that stops
an order being closed while it still owes money.

The two routers differ only in who they let near an order - a rider's own, or a
stall's own - which is exactly the part that cannot be shared. Everything after
that check is identical, and was not: pay on delivery shipped with collection
living inside the rider router, so a stall owner delivering their own order had
no way to take the money and no guard stopping them from closing the order
anyway. One copy is the fix for that, not a tidy-up.
"""

import base64
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.order import Order, OrderStatus
from app.db.models.payment import PaymentStatus
from app.modules.payments import razorpay

logger = logging.getLogger(__name__)


class CollectCash(BaseModel):
    """Whoever carried the order saying they took the money at the door.

    Cash only. UPI is not a thing the carrier gets to assert - Razorpay says
    when a QR was paid, through qr_code.credited, which is the whole reason the
    QR goes through a gateway rather than being the stall's own static code.
    """

    method: Literal["cash"] = "cash"


class UpiQrOut(BaseModel):
    """A single-use QR for exactly this order's total.

    Carries the image two ways on purpose. `image_png` is the picture itself,
    base64, fetched server-side so a phone that can reach this API can always
    show a code. `image_url` is Razorpay's own link, kept as the fallback for
    when that fetch did not work and for older app builds that only know about
    the URL. An app should prefer the bytes and fall back to the link.
    """

    image_url: str
    image_png: str | None = None
    amount: Decimal
    expires_at: datetime


async def close_upi_qr_later(qr_id: str, settings: Settings) -> None:
    """Shut a QR that is no longer collectable, without failing the request.

    Awaited rather than backgrounded because it is one bounded call and somebody
    is standing in front of a customer - but razorpay.close_upi_qr swallows its
    own failures, because a code that refuses to close is a nuisance, not a
    reason to refuse the collection that just succeeded.
    """
    await razorpay.close_upi_qr(qr_id, settings)


def assert_collectable(order: Order) -> None:
    """Whether there is money to take on this order right now.

    Says nothing about who is asking - the caller has already established that,
    and the two callers establish it differently.
    """
    if order.payment_status is PaymentStatus.PAID:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This order is already paid for")
    if order.payment_status is not PaymentStatus.DUE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "There is nothing to collect on this order"
        )
    if order.status is not OrderStatus.OUT_FOR_DELIVERY:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Collect when you are with the customer, after the order goes out.",
        )


def assert_nothing_left_to_collect(order: Order) -> None:
    """The single control that makes pay on delivery safe.

    Without it an order can be closed having collected nothing, and the stall
    has cooked food that is never paid for - which is the exposure the
    no-cash-on-delivery rule existed to avoid. It binds the stall as well as the
    rider: an owner who walks an order over themselves is the one holding the
    money, and a customer who refuses the order at the door is a cancellation,
    which waives the amount properly instead of leaving it owed forever.
    """
    if order.payment_status is PaymentStatus.DUE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Collect ₹{order.total_amount:.0f} before marking this delivered.",
        )


async def mark_cash_collected(
    order: Order, method: str, db: AsyncSession, settings: Settings
) -> None:
    """Taken on the carrier's word, which is the honest description of cash.

    Nobody else was there. The accountability is that the order is theirs, it is
    recorded against them, and the stall can see both the figure and that it was
    collected in cash rather than online.

    Only cash goes through here. UPI is marked paid by Razorpay's webhook, never
    by somebody tapping a button - that difference is the entire reason the QR
    is minted at the gateway.
    """
    order.payment_status = PaymentStatus.PAID
    order.collected_via = method
    if order.cod_qr_id:
        # Paid in cash after a QR was shown. Close it so the same order cannot
        # also be paid by somebody scanning a code that is still live.
        qr_id, order.cod_qr_id = order.cod_qr_id, None
        await db.commit()
        await close_upi_qr_later(qr_id, settings)
    else:
        await db.commit()


async def mint_upi_qr(order: Order, db: AsyncSession, settings: Settings) -> UpiQrOut:
    """A single-use QR for exactly this order's total.

    `single_use` closes it the moment one payment lands and `fixed_amount` locks
    it to the total, so it cannot be underpaid or reused for the next delivery.
    Razorpay then tells us it was paid through qr_code.credited, and the order
    marks itself - whoever is holding the phone never has to be believed.

    QR Codes is a product Razorpay activates on request, so a perfectly good
    account can still be unable to mint one. That answers 503 with something
    actionable rather than a stack trace: take the cash instead.
    """
    try:
        qr = await razorpay.create_upi_qr(
            amount=order.total_amount,
            description=f"Hungry Birds order {order.order_number}",
            notes={"order_id": str(order.id), "order_number": order.order_number},
            settings=settings,
        )
    except razorpay.RazorpayError as exc:
        if exc.is_feature_not_enabled:
            logger.error("razorpay QR codes are not enabled on this account: %s", exc)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "UPI collection isn't available right now. Please collect cash.",
            )
        logger.error("could not create a UPI QR for order %s: %s", order.id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Couldn't make a QR just now. Try again, or collect cash.",
        )

    image_url = str(qr.get("image_url") or "")
    if not image_url:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Couldn't make a QR just now. Try again, or collect cash.",
        )

    # Replacing an earlier QR for the same order: close the old one, so two live
    # codes cannot both take money for one delivery.
    previous = order.cod_qr_id
    order.cod_qr_id = str(qr.get("id") or "")[:32] or None
    await db.commit()
    if previous and previous != order.cod_qr_id:
        await close_upi_qr_later(previous, settings)

    # Fetched here rather than by the phone. See razorpay.fetch_qr_image: a
    # stall's wifi reaching our API says nothing about it reaching rzp.io, and
    # the failure lands on the one screen where a customer is waiting to pay.
    png = await razorpay.fetch_qr_image(image_url)

    return UpiQrOut(
        image_url=image_url,
        image_png=base64.b64encode(png).decode() if png else None,
        amount=order.total_amount,
        expires_at=datetime.fromtimestamp(int(qr["close_by"]), tz=timezone.utc)
        if qr.get("close_by")
        else datetime.now(timezone.utc) + timedelta(minutes=razorpay.QR_WINDOW_MINUTES),
    )


__all__ = [
    "CollectCash",
    "UpiQrOut",
    "assert_collectable",
    "assert_nothing_left_to_collect",
    "close_upi_qr_later",
    "mark_cash_collected",
    "mint_upi_qr",
]
