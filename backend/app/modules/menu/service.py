"""Pricing rules: who may change a price, and which price an order pays.

Two things live here and nowhere else.

`submit_price` decides what happens when a merchant sends a number. The live
price is never written by it - only `pending_price` - which is what makes the
approval gate structural rather than a matter of remembering to check a flag:
no pricing path can read the column the merchant writes.

`resolve_line_price` is the only code in the codebase that knows a dish can be
priced two ways. An item with no variants is priced by its own column; an item
with variants is priced by the one the customer chose, and its own column is
ignored. Keeping that in one function is what stops "which price?" becoming a
question every caller has to answer for itself.
"""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status

from app.db.models.menu import MenuItem, MenuItemVariant, MenuPriceChange, PriceChangeKind


def _same_money(a: Decimal | float | None, b: Decimal | float | None) -> bool:
    """Whether two prices are the same amount, however they were written.

    The merchant app sends JSON numbers, so 120, 120.0 and 120.00 all arrive for
    a price stored as Numeric(10,2). Comparing them raw would read an untouched
    price as a change and fill the admin queue with no-ops. Same trap, and the
    same answer, as _amounts_match in payments/service.py.
    """
    if a is None or b is None:
        return a is b
    return Decimal(str(a)).quantize(Decimal("0.01")) == Decimal(str(b)).quantize(Decimal("0.01"))


def record_price_change(
    db,
    *,
    vendor_id,
    kind: PriceChangeKind,
    name: str,
    new_price,
    old_price=None,
    item_id=None,
    variant_id=None,
    decided_by=None,
) -> None:
    """Append one row to the price history.

    Called for creations as well as changes, deliberately. Adding a dish is not
    gated, so a merchant refused a price can add a new dish at that price and
    delete the old one - a bypass that cannot be closed without gating creation,
    which was ruled out. Recording creations is what lets an admin see it
    happening rather than pretending the gate is airtight.
    """
    db.add(
        MenuPriceChange(
            vendor_id=vendor_id,
            item_id=item_id,
            variant_id=variant_id,
            name_snapshot=name[:255],
            old_price=old_price,
            new_price=new_price,
            kind=kind,
            decided_by=decided_by,
        )
    )


def submit_price(target: MenuItem | MenuItemVariant, price, db, *, vendor_id, name: str) -> str:
    """Take a merchant's proposed price and decide what it means.

    Returns what happened, so the caller can tell the merchant.

    The three cases exist because the merchant app sends `price` on every save,
    even when only a description changed. Treating "a price arrived" as "a price
    changed" would queue a pending approval every time somebody fixed a typo,
    and an admin could not tell those from real requests. So:

      unchanged, nothing pending  -> nothing happens
      unchanged, something pending -> the merchant typed the old number back,
                                      which means "never mind": withdraw it
      changed                      -> queue it, live price untouched

    This is the protection that matters, rather than the client-side "only send
    what changed" that goes with it: merchant phones do not update on command,
    and an old APK in the field must not be able to flood the queue.
    """
    is_variant = isinstance(target, MenuItemVariant)
    ids = {"variant_id": target.id, "item_id": target.item_id} if is_variant else {"item_id": target.id}

    if _same_money(price, target.price):
        if target.pending_price is None:
            return "unchanged"
        withdrawn = target.pending_price
        target.pending_price = None
        target.pending_price_at = None
        record_price_change(
            db,
            vendor_id=vendor_id,
            kind=PriceChangeKind.WITHDRAWN,
            name=name,
            new_price=withdrawn,
            old_price=target.price,
            **ids,
        )
        return "withdrawn"

    target.pending_price = price
    target.pending_price_at = datetime.now(timezone.utc)
    record_price_change(
        db,
        vendor_id=vendor_id,
        kind=PriceChangeKind.REQUESTED,
        name=name,
        new_price=price,
        old_price=target.price,
        **ids,
    )
    return "pending"


def apply_price_decision(
    target: MenuItem | MenuItemVariant, *, approve: bool, db, vendor_id, name: str, admin_id
) -> None:
    """Approve or reject whatever the merchant proposed.

    Approving is the only thing in the codebase that writes a live price after
    creation.
    """
    proposed = target.pending_price
    is_variant = isinstance(target, MenuItemVariant)
    ids = {"variant_id": target.id, "item_id": target.item_id} if is_variant else {"item_id": target.id}

    record_price_change(
        db,
        vendor_id=vendor_id,
        kind=PriceChangeKind.APPROVED if approve else PriceChangeKind.REJECTED,
        name=name,
        new_price=proposed,
        old_price=target.price,
        decided_by=admin_id,
        **ids,
    )
    if approve:
        target.price = proposed
    target.pending_price = None
    target.pending_price_at = None


def resolve_line_price(item: MenuItem, variant: MenuItemVariant | None) -> Decimal:
    """What one unit of this order line costs.

    The only place that knows an item can be priced two ways. Both mismatches
    are refused rather than guessed at: a dish with sizes has no meaningful
    single price, and a size sent for a dish that has none is a client that
    thinks it is ordering something else.
    """
    if item.variants:
        if variant is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Choose a size for {item.name}",
            )
        return variant.price
    if variant is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{item.name} does not come in sizes",
        )
    return item.price
