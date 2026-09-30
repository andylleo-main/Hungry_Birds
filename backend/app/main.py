import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import limits
from app.core.config import get_settings
from app.core.logging import install_log_redaction
from app.core.ratelimit import Limit, client_ip, consume, limit_by_ip
from app.core.redis import get_redis
from app.db.session import get_db
from app.modules.admin.router import analytics_router
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
from app.modules.media.router import router as media_router
from app.modules.fulfilment.router import router as fulfilment_router
from app.modules.menu.router import router as menu_router
from app.modules.orders.router import router as orders_router
from app.modules.orders.router import vendor_orders_router
from app.modules.realtime.router import router as realtime_router
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

if settings.cors_origin_list == ['*']:
    _startup_log.warning(
        'CORS_ORIGINS is "*": every website may call this API. The web app is '
        'served from this same origin, so the correct value is your own domain '
        '- or empty, which disables cross-origin access entirely.'
    )

app = FastAPI(title="Hungry Birds API")

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


@app.middleware('http')
async def enforce_request_limits(request: Request, call_next):
    path = request.url.path
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
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(analytics_router, prefix=API_PREFIX)
app.include_router(media_router, prefix=API_PREFIX)
app.include_router(orders_router, prefix=API_PREFIX)
app.include_router(vendor_orders_router, prefix=API_PREFIX)
app.include_router(realtime_router, prefix=API_PREFIX)


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
