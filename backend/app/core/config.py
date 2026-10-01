from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str

    resend_api_key: str = ""
    resend_from_email: str = "Hungry Birds <onboarding@resend.dev>"

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    # Riders have no refresh flow: they sign in at the start of a shift and must
    # not be logged out mid-delivery. Regenerating their password is what revokes
    # a token early, so a long life here is not an un-endable session.
    rider_token_expire_days: int = 14

    # "development" unlocks local conveniences (permissive CORS, the OTP debug
    # echo). Anything else - including the default - is treated as production,
    # so a deployment is safe unless someone deliberately declares otherwise.
    environment: str = "production"

    allowed_email_domain: str = "bitmesra.ac.in"

    # Makes this address an admin at startup, creating the account if it does not
    # exist yet. It breaks a deadlock that otherwise makes a fresh deployment
    # impossible to administer: promote_admin.py needs a user who has already
    # logged in, logging in needs an OTP email, and configuring email is itself
    # an admin task. Someone has to be let in first.
    #
    # Only the role is granted - no password, no session. It is idempotent, so
    # leaving it set is harmless, and it grants nothing to anybody who cannot
    # already set environment variables on this deployment (who could grant
    # themselves admin regardless).
    bootstrap_admin_email: str = ""

    # Creates the demo stalls at startup if they are missing. A Railway service
    # has no shell and its pre-deploy command is exec'd without one, so
    # scripts/seed.py cannot be run against a deployment - this is the way in.
    # Idempotent, so leaving it set only costs one query per boot, but it is still
    # worth unsetting once the real stalls are on.
    seed_demo_data: bool = False

    # Lets an admin sign in with a password instead of waiting on an OTP email,
    # which matters because the admin is the account you need when email itself
    # is the thing that is broken. Empty disables the endpoint entirely, so the
    # extra way in does not exist unless it is deliberately configured.
    # Generate with: python scripts/set_admin_password.py
    admin_password_hash: str = ""

    # Returns login codes in API responses. That is a complete authentication
    # bypass, so it is honoured only in development; see debug_echo_enabled.
    otp_debug_echo: bool = False

    # How many reverse proxies sit in front of this app. Railway is exactly one.
    # Used to find the real client address for rate limiting without trusting
    # the part of X-Forwarded-For that a caller can forge - see client_ip().
    # 0 means nothing is in front and the header is ignored entirely.
    trusted_proxy_count: int = 1

    # Bodies larger than this are refused before they are parsed, so a single
    # request cannot chew through memory.
    max_request_bytes: int = 256 * 1024

    # A blanket per-IP ceiling across the whole API, on top of the per-endpoint
    # limits. Generous enough that ordinary browsing never notices it.
    global_rate_limit_requests: int = 300
    global_rate_limit_seconds: int = 60

    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    cloudinary_upload_folder: str = "hungry_birds"

    # --- Firebase Cloud Messaging -------------------------------------------
    # Empty means "not configured", and the notification service then does
    # nothing rather than raising - the same convention as resend_api_key and
    # cloudinary_api_secret. A stall that gets no push still sees the order the
    # moment it opens the app, so this failing quietly is the right default.
    #
    # firebase_service_account_json is the whole service-account JSON file, as
    # one string. It is a credential: keep it in Railway's variables, never in
    # the repo.
    fcm_project_id: str = ""
    firebase_service_account_json: str = ""

    # --- Payments ------------------------------------------------------------
    # "cashfree" takes real money. "mock" confirms every payment instantly
    # without contacting anybody, so the rest of the system - the stall's queue,
    # the push, assignment, the handover code - can be exercised before the
    # gateway credentials exist.
    #
    # There is no safe default but the real one, so this is not inferred from
    # anything. Mock mode is on only when somebody has typed it into an
    # environment variable, and the app logs a warning on every boot while it is.
    payments_mode: str = "cashfree"

    # --- Cashfree (payments) -------------------------------------------------
    # Empty secret means Cashfree is not configured: the checkout endpoint
    # answers 503 and the webhook 404s rather than advertising a door it cannot
    # verify anybody through.
    #
    # The secret key is both the API credential and the key Cashfree signs
    # webhooks with, so it never belongs anywhere near the browser bundle.
    cashfree_app_id: str = ""
    cashfree_secret_key: str = ""
    cashfree_api_version: str = "2025-01-01"
    # "sandbox" or "production". Sent to the browser with the payment session so
    # the SDK opens against the same environment the session was minted in -
    # hardcoding it into the bundle is how those two drift apart.
    cashfree_env: str = "sandbox"
    # How long a customer has to finish paying. Must stay comfortably below the
    # local sweep window, so we never give up on an order Cashfree would still
    # accept money for.
    cashfree_order_expiry_minutes: int = 15
    # Rejects a replayed webhook whose signature is still valid but whose
    # timestamp is old.
    cashfree_webhook_tolerance_seconds: int = 300
    # Where the browser is sent back to after the hosted flow, and where Cashfree
    # posts webhooks. Both must be the public URL of this deployment.
    public_base_url: str = ""

    # Empty means send no CORS headers at all, which is correct in production:
    # the backend serves the web app itself, so every call is same-origin and
    # no other site has any business calling this API. Set it to a
    # comma-separated origin list only if a separate frontend host is added.
    cors_origins: str = ""

    @field_validator("database_url")
    @classmethod
    def use_async_driver(cls, value: str) -> str:
        """Railway (and most hosts) inject a plain postgres:// URL, but the
        async engine needs the asyncpg driver spelled out."""
        for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
            if value.startswith(prefix):
                return value
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator("payments_mode")
    @classmethod
    def known_payments_mode(cls, value: str) -> str:
        """A typo here must not fall back to taking real money, nor to giving food
        away. Refusing to boot is the only outcome that is wrong in neither
        direction."""
        mode = value.strip().lower()
        if mode not in ("cashfree", "mock"):
            raise ValueError('PAYMENTS_MODE must be "cashfree" or "mock"')
        return mode

    @property
    def payments_mock(self) -> bool:
        """Every payment confirms instantly and no money moves."""
        return self.payments_mode == "mock"

    @property
    def cashfree_configured(self) -> bool:
        """Whether we hold credentials to talk to Cashfree and to verify what it
        sends us.

        Separate from payments_enabled below, and the distinction is load-bearing:
        the webhook is gated on *this* one. The secret key is the HMAC key
        webhook signatures are checked against, so a route that accepts webhooks
        without it would verify every forgery against an empty key - and in mock
        mode there is no secret, which is exactly when payments_enabled is true.
        """
        return bool(self.cashfree_app_id and self.cashfree_secret_key)

    @property
    def payments_enabled(self) -> bool:
        """Whether an order can be paid for at all, by any means."""
        return self.payments_mock or self.cashfree_configured

    @property
    def cashfree_base_url(self) -> str:
        return (
            "https://api.cashfree.com/pg"
            if self.cashfree_env == "production"
            else "https://sandbox.cashfree.com/pg"
        )

    @property
    def push_enabled(self) -> bool:
        return bool(self.fcm_project_id and self.firebase_service_account_json)

    @property
    def is_development(self) -> bool:
        return self.environment.strip().lower() in {"development", "dev", "local"}

    @property
    def debug_echo_enabled(self) -> bool:
        """OTP codes echoed in responses - development only.

        Deliberately gated on two settings rather than one. OTP_DEBUG_ECHO is
        the kind of variable that gets copied into a production environment by
        accident, and on its own it would hand anyone a login as anyone,
        including the admin. Requiring ENVIRONMENT=development as well means
        that mistake is inert.
        """
        return self.otp_debug_echo and self.is_development

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        if not origins and self.is_development:
            # The web app runs on Vite's port in development while the API is
            # on this one, so local work does need cross-origin access.
            return [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:4173",
                "http://127.0.0.1:4173",
            ]
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
