import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.bootstrap import ensure_bootstrap_admin
from app.core.config import Settings, get_settings
from app.core.logging import install_log_redaction
from app.core.ratelimit import Limit, client_ip, consume, limit_by_ip
from app.core.redis import get_redis
from app.db.session import async_session_factory, get_db
from app.modules.admin.menu_router import router as admin_menu_router
from app.modules.admin.router import analytics_router
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
from app.modules.media.router import router as media_router
from app.modules.fulfilment.router import router as fulfilment_router
from app.modules.menu.router import router as menu_router
from app.modules.notifications.router import router as devices_router
from app.modules.orders.router import router as orders_router
from app.modules.payments.router import order_payments_router
from app.modules.payments.router import router as payments_router
from app.modules.orders.router import vendor_orders_router
from app.modules.realtime.router import router as realtime_router
from app.modules.riders.router import auth_router as rider_auth_router
from app.modules.riders.router import rider_router
from app.modules.riders.router import router as riders_router
from app.modules.vendors.router import router as vendors_router

settings = get_settings()

install_log_redaction()

_startup_log = logging.getLogger('uvicorn.error')

if settings.debug_echo_enabled:
    _startup_log.warning(
        'OTP_DEBUG_ECHO is ON: login codes are returned in API responses. '
        'This is a full authentication bypass - never run a public deployment '
        'with it enabled.'
    )
elif settings.otp_debug_echo:
    _startup_log.info(
        'OTP_DEBUG_ECHO is set but ignored because ENVIRONMENT is not '
        'development. Login codes will not be echoed.'
    )

if settings.payments_mock:
    _startup_log.warning(
        'PAYMENTS_MODE=mock: every order is marked paid without any money '
        'changing hands, and the Cashfree webhook is disabled. Fine for testing '
        'the flow; on a deployment students can reach, it is free food. Set '
        'PAYMENTS_MODE=cashfree once the gateway credentials are in place.'
    )
elif not settings.cashfree_configured:
    _startup_log.warning(
        'Cashfree is not configured, so nothing can be ordered: placing an '
        'order answers 503. Set CASHFREE_APP_ID and CASHFREE_SECRET_KEY, or '
        'PAYMENTS_MODE=mock to test without a gateway.'
    )

if settings.cors_origin_list == ['*']:
    _startup_log.warning(
        'CORS_ORIGINS is "*": every website may call this API. The web app is '
        'served from this same origin, so the correct value is your own domain '
        '- or empty, which disables cross-origin access entirely.'
    )

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup work that has to happen against a live database.

    Only the admin bootstrap, which does nothing unless BOOTSTRAP_ADMIN_EMAIL is
    set and never raises - the API must come up even if it fails, since an
    instance nobody can administer still serves students and stalls.

    Migrations are deliberately not here: they run as Railway's preDeployCommand,
    once per deploy, rather than racing between replicas on boot.
    """
    async with async_session_factory() as db:
        await ensure_bootstrap_admin(settings, db)

        if settings.seed_demo_data:
            # Same reasoning as the bootstrap above: a failure here must not stop
            # the API serving, because demo data is a convenience and an instance
            # that will not boot is not.
            try:
                from app.core.demo_data import seed_demo_stalls

                created = await seed_demo_stalls(db)
                if created:
                    _startup_log.warning(
                        'SEED_DEMO_DATA: created demo stalls %s. Unset the variable '
                        'once real stalls are on.',
                        ', '.join(created),
                    )
            except Exception:
                _startup_log.exception('SEED_DEMO_DATA could not be applied')
                await db.rollback()
    yield


app = FastAPI(title="Hungry Birds API", lifespan=lifespan)

# A blanket ceiling per address, underneath the per-endpoint limits in
# app/core/limits.py. Those are sized for each endpoint's specific abuse; this
# one catches the general case - a client hammering the API broadly, or
# spreading a scrape across many endpoints to stay under each individual cap.
_GLOBAL_LIMIT = (Limit(settings.global_rate_limit_requests, settings.global_rate_limit_seconds),)

# Exempt from both middlewares below. Static assets are many-per-pageload and
# served from memory. /health is a bare liveness reply that touches nothing, and
# the platform polls it on a schedule - throttling it would read as a dead
# service and roll the release back. /health/ready is deliberately NOT exempt:
# it queries Postgres and pings Redis, so it gets its own generous limit on the
# route itself rather than a free pass.
_UNMETERED_PREFIXES = ('/assets/', '/favicon')
_UNMETERED_PATHS = ('/health',)

# Exempt from the per-IP ceiling only - the body-size guard below still applies.
#
# Every Cashfree delivery arrives from their infrastructure, so they all land in
# one address bucket and a busy lunchtime would throttle them collectively. A
# throttled webhook is a 429, which Cashfree retries, which builds a backlog that
# cannot drain - and the thing being lost is notification that somebody has
# already been charged. The route has its own generous, signature-gated limit.
_UNTHROTTLED_PATHS = ('/api/payments/cashfree/webhook',)


@app.middleware('http')
async def enforce_request_limits(request: Request, call_next):
    # The ASGI scope path, not request.url.path. They are normally identical, but
    # request.url is rebuilt by concatenating scheme, host and path and re-parsing
    # the result, so a path that moves the authority boundary during that re-parse
    # can make the two disagree (Starlette PYSEC-2026-161 and -248). Routing uses
    # the scope path, so anything deciding who gets past a limiter has to use the
    # same string the router will - otherwise an exemption could be granted for a
    # path that is not the one being served.
    path = request.scope.get('path', '')
    if path in _UNMETERED_PATHS or path.startswith(_UNMETERED_PREFIXES):
        return await call_next(request)

    # Refuse an oversized body before anything tries to buffer or parse it.
    declared = request.headers.get('content-length')
    if declared is not None:
        try:
            if int(declared) > settings.max_request_bytes:
                return JSONResponse(
                    {'detail': 'Request body too large'},
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
        except ValueError:
            return JSONResponse(
                {'detail': 'Invalid Content-Length'},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    if path in _UNTHROTTLED_PATHS:
        return await call_next(request)

    try:
        await consume(
            get_redis(),
            'global',
            f'ip:{client_ip(request, settings)}',
            _GLOBAL_LIMIT,
        )
    except HTTPException as exc:
        return JSONResponse(
            {'detail': exc.detail},
            status_code=exc.status_code,
            headers=exc.headers or {},
        )

    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # Deliberately False. Auth is a Bearer token held in the client and set
    # explicitly on each request, never a cookie, so "credentials" in the CORS
    # sense are not used. Pairing allow_credentials=True with an "*" origin is
    # the dangerous combination - it tells the browser any site may make
    # credentialed cross-origin calls. Turning it off keeps the Authorization
    # header working (that is an ordinary request header, covered by
    # allow_headers) while removing that grant.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Everything the API serves lives under /api so it can never collide with a
# client-side route of the same name. Without this the SPA's /orders/<id>
# tracking page is shadowed by GET /orders/{order_id} and a refresh returns
# 401 JSON instead of the page.
API_PREFIX = '/api'

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(vendors_router, prefix=API_PREFIX)
app.include_router(menu_router, prefix=API_PREFIX)
app.include_router(fulfilment_router, prefix=API_PREFIX)
app.include_router(devices_router, prefix=API_PREFIX)
app.include_router(riders_router, prefix=API_PREFIX)
app.include_router(rider_auth_router, prefix=API_PREFIX)
app.include_router(rider_router, prefix=API_PREFIX)
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(admin_menu_router, prefix=API_PREFIX)
app.include_router(analytics_router, prefix=API_PREFIX)
app.include_router(media_router, prefix=API_PREFIX)
app.include_router(orders_router, prefix=API_PREFIX)
app.include_router(order_payments_router, prefix=API_PREFIX)
app.include_router(payments_router, prefix=API_PREFIX)
app.include_router(vendor_orders_router, prefix=API_PREFIX)
app.include_router(realtime_router, prefix=API_PREFIX)


@app.get(API_PREFIX + "/config")
async def public_config(config: Settings = Depends(get_settings)) -> dict[str, str]:
    """The handful of server facts the web app cannot hardcode without drifting.

    Public and unauthenticated, which is fine: the payment mode is already
    returned to any signed-in customer with their payment session, and it is a
    statement about this deployment rather than about anybody using it. The web
    app reads it to warn, on the checkout page, that nothing is really being
    charged - a banner nobody can miss being the difference between a test
    deployment and a misunderstanding.
    """
    return {"payments_mode": config.payments_mode}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/health/ready",
    dependencies=[Depends(limit_by_ip("health_ready", *limits.HEALTH_READY))],
)
async def readiness(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> dict[str, str]:
    """Fails unless both Postgres and Redis actually answer, so a passing
    deploy healthcheck means the service can really serve traffic."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"database unreachable: {exc}")

    try:
        await redis.ping()
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"redis unreachable: {exc}")

    return {"status": "ready", "database": "ok", "redis": "ok"}


# --- Customer web app -------------------------------------------------------
#
# The built SPA is copied to backend/static by the Docker build. Serving it
# from this same service keeps the frontend on the API's own origin, so there
# is no CORS to configure, no second domain, and no second service to pay for.
# The directory is absent in local backend-only development, so everything
# below is conditional and the API runs exactly as before without it.

STATIC_DIR = Path(__file__).resolve().parent.parent / 'static'

if (STATIC_DIR / 'index.html').is_file():
    # Hashed build assets: safe to cache hard, since the filename changes
    # whenever the contents do.
    app.mount(
        '/assets',
        StaticFiles(directory=STATIC_DIR / 'assets'),
        name='assets',
    )

    @app.get('/{full_path:path}', include_in_schema=False)
    async def spa(request: Request, full_path: str) -> FileResponse:
        """Serve a real file when there is one, otherwise the app shell.

        React Router owns paths like /orders/<id>, so a refresh or a shared
        link must still return index.html rather than a 404.

        But the build also drops files at the root of the bundle - the favicon,
        the logo, touch icons - and those are not client-side routes. Until
        this checked for them, every one of them fell through to the fallback
        and was answered with index.html: the browser asked for a PNG, got
        HTML, and quietly showed no icon at all. Checking the filesystem first
        covers whatever the build emits next (a manifest, robots.txt) without
        another hardcoded route.

        An unknown /api or /health path 404s as JSON rather than being handed
        the HTML shell, which would otherwise reach the client as a confusing
        "Unexpected token '<'" JSON parse error.
        """
        if full_path.startswith(('api/', 'health')):
            raise HTTPException(status.HTTP_404_NOT_FOUND, 'Not found')

        if full_path:
            candidate = (STATIC_DIR / full_path).resolve()
            # Confine to the bundle: without this, a path like ../../.env walks
            # out of the static directory and serves whatever it lands on.
            if candidate.is_file() and candidate.is_relative_to(STATIC_DIR.resolve()):
                return FileResponse(candidate)

        return FileResponse(STATIC_DIR / 'index.html')
