"""Talking to Firebase Cloud Messaging's HTTP v1 API.

Kept separate from the "what do we notify people about" logic so that the part
which knows about OAuth assertions and Google's error codes does not also know
about orders.

HTTP v1 rather than the old legacy API, because the legacy server key was shut
down in 2024. It wants an OAuth2 bearer token minted from the service account,
which is why google-auth is a dependency - there is no firebase-admin SDK here,
since all that is needed is the token.
"""

import json
import logging
import time

import anyio
import httpx
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleAuthRequest

from app.core.config import Settings

logger = logging.getLogger(__name__)

_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"

# Google's tokens last an hour. Refreshing a minute early avoids racing the
# expiry on a request that takes a moment to arrive.
_REFRESH_MARGIN_SECONDS = 60

# FCM says a token is dead with one of these. Anything else - a 500, a timeout,
# a quota error - is about Google or us, and must not cause us to throw away a
# device that is perfectly fine.
DEAD_TOKEN_CODES = frozenset({"UNREGISTERED", "INVALID_ARGUMENT", "NOT_FOUND"})


class _TokenCache:
    """One access token, refreshed when it is about to expire.

    Minting a token signs a JWT and makes a round trip to Google. Doing that per
    push would add a second of latency to every order and burn quota, so it is
    held for the hour it is valid.
    """

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = anyio.Lock()

    async def get(self, settings: Settings) -> str:
        async with self._lock:
            if self._token and time.time() < self._expires_at - _REFRESH_MARGIN_SECONDS:
                return self._token

            info = json.loads(settings.firebase_service_account_json)
            creds = service_account.Credentials.from_service_account_info(info, scopes=[_SCOPE])
            # Signing and the token round trip are both synchronous and neither
            # is fast, so they go to a worker thread rather than stalling the
            # event loop for every request in flight.
            await anyio.to_thread.run_sync(lambda: creds.refresh(GoogleAuthRequest()))

            self._token = creds.token
            self._expires_at = creds.expiry.timestamp() if creds.expiry else time.time() + 3000
            return self._token


_tokens = _TokenCache()


async def send_to_token(
    token: str,
    *,
    title: str,
    body: str,
    data: dict[str, str],
    channel_id: str,
    settings: Settings,
    client: httpx.AsyncClient,
) -> str | None:
    """Push one message. Returns an FCM error code when the token is dead.

    A dead token is a normal, expected outcome - apps get uninstalled - so it is
    reported as a value for the caller to act on. Everything else raises, and the
    caller's fire_and_log turns it into a log line rather than a failed order.
    """
    access_token = await _tokens.get(settings)
    response = await client.post(
        _ENDPOINT.format(project=settings.fcm_project_id),
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                # Strings only: FCM rejects a data payload with any other type,
                # and does so with a 400 that does not say which key.
                "data": {k: str(v) for k, v in data.items()},
                "android": {
                    # A stall needs to hear this during a lunch rush, so it must
                    # survive Doze rather than being batched until the phone
                    # next wakes up on its own.
                    "priority": "HIGH",
                    # Named by the caller because the channel is per-app, and
                    # the two apps mean different things by a notification. The
                    # id has to match a channel the receiving app actually
                    # created in its MainActivity - Android silently demotes a
                    # message naming one that does not exist to a low-importance
                    # default, which is a silent phone and no error anywhere.
                    "notification": {"channel_id": channel_id, "sound": "default"},
                },
            }
        },
    )

    if response.status_code < 300:
        return None

    code = _error_code(response)
    if code in DEAD_TOKEN_CODES:
        return code

    # Raised so fire_and_log records what Google actually said; guessing from a
    # status code alone is how push outages stay mysterious.
    response.raise_for_status()
    return None


def _error_code(response: httpx.Response) -> str | None:
    """FCM's machine-readable reason, if the body has one."""
    try:
        payload = response.json()
    except ValueError:
        return None
    error = payload.get("error", {})
    for detail in error.get("details", []):
        if detail.get("@type", "").endswith("FcmError"):
            return detail.get("errorCode")
    return error.get("status")
