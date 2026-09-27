import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import install_log_redaction
from app.core.redis import get_redis
from app.db.session import get_db
from app.modules.admin.router import router as admin_router
from app.modules.auth.router import router as auth_router
from app.modules.media.router import router as media_router
from app.modules.menu.router import router as menu_router
from app.modules.orders.router import router as orders_router
from app.modules.orders.router import vendor_orders_router
from app.modules.realtime.router import router as realtime_router
from app.modules.vendors.router import router as vendors_router

settings = get_settings()

install_log_redaction()

if settings.otp_debug_echo:
    logging.getLogger('uvicorn.error').warning(
        'OTP_DEBUG_ECHO is ON: login codes are returned in API responses. '
        'This is a full authentication bypass - never run a public deployment '
        'with it enabled.'
    )

app = FastAPI(title="Hunger Birds API")

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
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(media_router, prefix=API_PREFIX)
app.include_router(orders_router, prefix=API_PREFIX)
app.include_router(vendor_orders_router, prefix=API_PREFIX)
app.include_router(realtime_router, prefix=API_PREFIX)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
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

    @app.get('/favicon.svg', include_in_schema=False)
    async def favicon() -> FileResponse:
        return FileResponse(STATIC_DIR / 'favicon.svg')

    @app.get('/{full_path:path}', include_in_schema=False)
    async def spa(request: Request, full_path: str) -> FileResponse:
        """History fallback for client-side routes.

        React Router owns paths like /orders/<id>, so a refresh or a shared
        link must still return index.html rather than a 404.

        An unknown /api or /health path 404s as JSON rather than being handed
        the HTML shell, which would otherwise reach the client as a confusing
        "Unexpected token '<'" JSON parse error.
        """
        if full_path.startswith(('api/', 'health')):
            raise HTTPException(status.HTTP_404_NOT_FOUND, 'Not found')
        return FileResponse(STATIC_DIR / 'index.html')
