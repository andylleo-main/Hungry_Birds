import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints, field_validator

from app.core.fields import Name

# Lowercase letters, digits and dashes. Deliberately narrow: this is typed on a
# phone keyboard at the start of a shift, so no spaces, no case to get wrong, and
# nothing that looks different in two fonts.
LoginId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=32),
]


class RiderCreate(BaseModel):
    display_name: Name
    # Normalised to E.164 by the router, which rejects anything that is not a
    # real Indian mobile. The cap here only stops an absurd value reaching it.
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)]
    # Optional: left out, the server suggests one from the rider's name. A
    # merchant who wants "amit" rather than "amit-4821" can say so.
    login_id: LoginId | None = None

    @field_validator("login_id")
    @classmethod
    def login_id_shape(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not all(ch.isalnum() or ch == "-" for ch in v) or not v[0].isalnum():
            raise ValueError("login id may use letters, numbers and dashes, and must start with one")
        return v


class RiderUpdate(BaseModel):
    display_name: Name | None = None
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    is_active: bool | None = None


class RiderOut(BaseModel):
    """A rider as the merchant's list shows them.

    Has no password field, and that is structural rather than a matter of
    remembering to exclude one: the only schema that can carry a password is
    RiderCredentials below, so no amount of editing this model can start leaking
    one into a list response.
    """

    id: uuid.UUID
    login_id: str
    display_name: str
    phone: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class RiderCredentials(RiderOut):
    """Returned only when a password is created or regenerated.

    The plaintext exists in this one response and nowhere else - it is never
    stored, so this is the only chance to write it down. The merchant app says
    so, and offers Regenerate for when nobody did.
    """

    password: str


class RiderLogin(BaseModel):
    login_id: LoginId
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class RiderTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rider: RiderOut
    stall_name: str
