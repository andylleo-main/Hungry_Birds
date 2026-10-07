import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.db.models.cashback import CashbackKind, CashbackReason


class WalletOut(BaseModel):
    """One of the two balances.

    Both are always returned, including the empty one, so the offers page can
    draw both and explain the difference rather than silently hiding a wallet a
    student has not earned into yet. Somebody who has never been to Gourmet
    Kitchen should still find out that going there pays back more.
    """

    kind: CashbackKind
    balance: Decimal
    # The percentage this wallet earns and may be spent at - the same number for
    # both, per the scheme - and the most one order can earn.
    percent: int
    cap: Decimal
    # The soonest unexpired credit's date, so the page can warn rather than
    # letting a student discover expiry by losing a balance.
    expires_next: datetime | None


class EntryOut(BaseModel):
    """One movement, for the "show me where this came from" list."""

    id: uuid.UUID
    kind: CashbackKind
    amount: Decimal
    reason: CashbackReason
    order_id: uuid.UUID | None
    # Carried so the list can say which stall, without the client fetching each
    # order. Null where the order has since been deleted.
    stall_name: str | None
    order_number: str | None
    expires_at: datetime | None
    created_at: datetime


class CashbackOut(BaseModel):
    wallets: list[WalletOut]
    entries: list[EntryOut]


class QuoteOut(BaseModel):
    """What would actually come off this cart.

    Computed by the same function the order path calls, so the figure shown at
    checkout and the figure charged cannot disagree. That is the whole reason
    this endpoint exists rather than the client doing the percentage itself.
    """

    kind: CashbackKind
    # What is in the matching wallet.
    balance: Decimal
    # What may be applied to this cart: the smallest of the percentage ceiling,
    # the balance, and the cart.
    redeemable: Decimal
    # What the cart would cost after it.
    payable: Decimal
    # The ceiling that bound, so the page can explain itself: "20% of your cart"
    # reads very differently from "all the cashback you have".
    percent: int
