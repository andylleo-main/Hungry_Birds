import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.db.models.coupon import (
    CouponAudience,
    DiscountType,
    ExpiryType,
    RedemptionState,
)


class CouponCheckIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    vendor_id: uuid.UUID
    # The client's figure for the cart. Used for this answer and nothing else -
    # the real discount is worked out again in place_order from the basket the
    # server priced itself, so a client that lies here only lies to its own
    # screen.
    subtotal: Decimal = Field(ge=0, le=100000, decimal_places=2)


class CouponOut(BaseModel):
    """A coupon as a customer sees it: what it does, never how many are left."""

    code: str
    description: str | None
    discount_type: DiscountType
    discount_value: Decimal
    max_discount: Decimal | None
    min_order_value: Decimal
    # True when it works at every stall, which the card renders as "At any stall".
    all_stalls: bool
    # The stalls it is pinned to, when it is not. Names rather than ids: nothing
    # a customer sees needs the id, and a name is what they would recognise.
    stall_names: list[str]
    # True when it applies itself without being typed.
    automatic: bool
    # What it would take off the cart that was asked about.
    discount: Decimal


class AdminCouponIn(BaseModel):
    """What the admin's form sends. Validated here rather than in the handler."""

    code: str = Field(min_length=1, max_length=32)
    # Where it works: everywhere, or at the stalls listed below. Defaults to
    # everywhere, which is both the common case and what an older caller that
    # sends neither field means.
    all_stalls: bool = True
    # Read only when `all_stalls` is false. Capped at a number no campus will
    # reach, for the reason the email list is: this is one row each.
    vendor_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    discount_type: DiscountType
    discount_value: Decimal = Field(gt=0, le=100000, decimal_places=2)
    max_discount: Decimal | None = Field(default=None, gt=0, le=100000, decimal_places=2)
    expiry_type: ExpiryType
    max_uses: int | None = Field(default=None, ge=1, le=1000000)
    expires_at: datetime | None = None
    min_order_value: Decimal = Field(default=Decimal("0"), ge=0, le=100000, decimal_places=2)
    audience: CouponAudience = CouponAudience.ANYONE
    # Only read when the audience is NAMED. Capped because this is one row each
    # and an admin pasting a mailing list into it is a different feature.
    audience_emails: list[EmailStr] = Field(default_factory=list, max_length=500)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool = True
    one_per_customer: bool = True
    show_in_offers: bool = False

    @model_validator(mode="after")
    def expiry_matches_its_type(self) -> "AdminCouponIn":
        """A count-based coupon needs a count; a dated one needs a date.

        Refused rather than defaulted, because both silent defaults are bad: an
        unlimited code that was meant to be capped is money, and a code that
        expires immediately is a support ticket.
        """
        if self.expiry_type is ExpiryType.COUNT and self.max_uses is None:
            raise ValueError("A count-based coupon needs a maximum number of uses")
        if self.expiry_type is ExpiryType.DATE and self.expires_at is None:
            raise ValueError("A date-based coupon needs an expiry date")
        return self

    @model_validator(mode="after")
    def percent_is_a_percentage(self) -> "AdminCouponIn":
        """100% off is allowed; 120% off is a typo.

        The floor in the service keeps even a 100% coupon from zeroing an order,
        so this is about catching a slip at the point it is made rather than
        about protecting the money.
        """
        if self.discount_type is DiscountType.PERCENT and self.discount_value > 100:
            raise ValueError("A percentage discount cannot be more than 100%")
        return self

    @model_validator(mode="after")
    def named_coupons_name_somebody(self) -> "AdminCouponIn":
        if self.audience is CouponAudience.NAMED and not self.audience_emails:
            raise ValueError("Add at least one email address, or change who can use it")
        return self

    @model_validator(mode="after")
    def a_narrowed_coupon_names_a_stall(self) -> "AdminCouponIn":
        """Picking "only these stalls" and then picking none is not a setting.

        Refused rather than read as either thing it could mean. Treating it as
        "everywhere" would hand the campus a code meant for one kitchen, and
        saving it as a coupon that works nowhere would be a code an admin thinks
        they have made. The same shape as the NAMED check above, for the same
        reason: a narrowing that narrows to nothing is a slip.
        """
        if not self.all_stalls and not self.vendor_ids:
            raise ValueError("Pick at least one stall, or let it work at every stall")
        return self


class AdminCouponOut(BaseModel):
    """A coupon as the admin screen shows it, with its usage worked out."""

    id: uuid.UUID
    code: str
    all_stalls: bool
    # Both, because the screen needs both: the ids to re-tick the form, the names
    # to put in the list without a second lookup. Empty while `all_stalls` is on.
    vendor_ids: list[uuid.UUID]
    stall_names: list[str]
    discount_type: DiscountType
    discount_value: Decimal
    max_discount: Decimal | None
    expiry_type: ExpiryType
    max_uses: int | None
    expires_at: datetime | None
    min_order_value: Decimal
    audience: CouponAudience
    audience_emails: list[str]
    description: str | None
    is_active: bool
    one_per_customer: bool
    show_in_offers: bool
    created_at: datetime

    # Derived from the redemption rows every time it is asked for, so it cannot
    # drift from them. Held uses count: one reserved by an order somebody is
    # still paying for is not available to anybody else.
    uses: int


class RedemptionOut(BaseModel):
    """One use, for the admin's log."""

    id: uuid.UUID
    code: str
    customer_email: str
    order_id: uuid.UUID | None
    order_number: str | None
    discount: Decimal
    state: RedemptionState
    created_at: datetime
    settled_at: datetime | None
