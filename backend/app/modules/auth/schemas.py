import uuid

from pydantic import BaseModel, EmailStr, field_validator

from app.db.models.user import UserRole


class OTPRequest(BaseModel):
    email: EmailStr


class OTPRequestResponse(BaseModel):
    message: str
    debug_code: str | None = None


class OTPVerify(BaseModel):
    email: EmailStr
    code: str

    @field_validator("code")
    @classmethod
    def code_must_be_six_digits(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 6:
            raise ValueError("code must be a 6-digit number")
        return v


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    phone: str | None
    role: UserRole

    model_config = {"from_attributes": True}


class UpdateMe(BaseModel):
    full_name: str | None = None
    phone: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
