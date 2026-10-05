import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, StringConstraints, field_validator

from app.core.fields import Name
from app.db.models.user import UserRole


class OTPRequest(BaseModel):
    email: EmailStr


class OTPRequestResponse(BaseModel):
    message: str
    debug_code: str | None = None
    # How long before another code may be requested. The login page counts down
    # with it instead of hard-coding a guess that could drift from the server.
    resend_after_seconds: int


class OTPVerify(BaseModel):
    email: EmailStr
    code: str

    @field_validator("code")
    @classmethod
    def code_must_be_six_digits(cls, v: str) -> str:
        # Deliberately not str.isdigit(), which is True for non-ASCII digits
        # such as Arabic-Indic "\u0661\u0662\u0663\u0664\u0665\u0666". Those would pass this check and then
        # reach secrets.compare_digest, which raises TypeError on any
        # non-ASCII string - turning a bad code into a 500 instead of a clean
        # rejection. ASCII digits only, so the comparison downstream is always
        # safe.
        if len(v) != 6 or not all(c in "0123456789" for c in v):
            raise ValueError("code must be a 6-digit number")
        return v


class AdminLogin(BaseModel):
    email: EmailStr
    # Bounded only to keep an absurd value out of the hashing function; there
    # is no upper limit on a sensible password's length.
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class VendorLogin(BaseModel):
    """A stall owner signing in without waiting for a code.

    The login id is the email, so there is nothing new to issue, lose or ask for
    again. Stall accounts are not restricted to the campus domain, which is why
    this route does not call assert_allowed_domain.
    """

    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class SetVendorPassword(BaseModel):
    """Choosing or changing a stall password.

    Eight characters rather than the twelve the admin script demands. This is
    typed one-handed on a phone at the start of a shift, and it is paired with a
    fail-closed rate limiter; a floor high enough to be resented is a floor that
    gets written on the till.
    """

    password: Annotated[str, StringConstraints(min_length=8, max_length=256)]


class VendorPasswordState(BaseModel):
    """Whether this account has a password yet, so the app knows to ask."""

    is_set: bool


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    phone: str | None
    role: UserRole

    model_config = {"from_attributes": True}


class UpdateMe(BaseModel):
    full_name: Name | None = None
    # Normalised to E.164 by the router; the length cap only stops an absurd
    # value reaching the normaliser.
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class RefreshRequest(BaseModel):
    refresh_token: Annotated[str, StringConstraints(min_length=1, max_length=512)]


class AccessTokenResponse(BaseModel):
    access_token: str
    # Rotated on every refresh, so the client must store this one and discard
    # the token it sent. Reusing the old one now ends the session.
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class SessionOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    user_agent: str | None
    # True for the device asking, so the UI can label it "this device" rather
    # than inviting someone to sign themselves out by mistake.
    current: bool = False

    model_config = {"from_attributes": True}
