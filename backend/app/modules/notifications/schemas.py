from typing import Annotated

from pydantic import BaseModel, StringConstraints

# Matches the String(512) column. FCM tokens are long and Google documents no
# ceiling, so this is sized generously rather than precisely.
FcmToken = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=512)]


class DeviceRegister(BaseModel):
    fcm_token: FcmToken
    platform: Annotated[str, StringConstraints(strip_whitespace=True, max_length=16)] = "android"


class DeviceOut(BaseModel):
    fcm_token: str
    platform: str

    model_config = {"from_attributes": True}
