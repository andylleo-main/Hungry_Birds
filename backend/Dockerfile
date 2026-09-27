# Build context is the REPOSITORY ROOT, not backend/, because stage 1 needs
# apps/web. Railway must therefore have Root Directory unset (repo root) with
# dockerfilePath "backend/Dockerfile" - see railway.json and the README.
#
# Why a Dockerfile rather than Railway's Nixpacks builder: SQLAlchemy's async
# engine routes every query through greenlet, whose compiled extension links
# against libstdc++.so.6. The Nix-based image didn't have that on the loader
# path, so the app booted and served /health but raised
#
#   ValueError: the greenlet library is required to use this function.
#   libstdc++.so.6: cannot open shared object file
#
# on the first database call, and on `alembic upgrade head`. Pinning a Debian
# base makes the C runtime predictable instead of rediscovered per deploy.

# --- Stage 1: build the customer web app ------------------------------------
FROM node:22-slim AS web

WORKDIR /web

# Lockfile first so the dependency layer caches across code-only changes.
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

COPY apps/web/ ./
# No VITE_API_BASE_URL: the backend serves this bundle, so the API is
# same-origin and the deployed hostname never has to be baked in.
RUN npm run build

# --- Stage 2: the API, which also serves the built app ----------------------
#
# The full image rather than -slim, and deliberately so. greenlet's compiled
# extension links against libstdc++.so.6, which python:3.11-slim does not ship:
# the official slim build compiles Python, then purges its build dependencies,
# and the C++ runtime goes with them. That was the cause of the greenlet crash
# described above.
#
# The obvious fix - `apt-get install libstdc++6` on top of slim - is what this
# replaced, because it failed on Railway's builder: apt died three seconds into
# the build, before it could fetch a single index. Whether that was a transient
# mirror problem or the builder having no route to deb.debian.org, the build
# had a hard dependency on reaching a Debian mirror at image-build time, and it
# only had that dependency to reinstate a library the base image had just
# thrown away.
#
# python:3.11 is built on buildpack-deps, keeps g++ and never purges it, so the
# C++ runtime is simply there. No apt step, no network round trip, nothing to
# be flaky. The cost is image size, roughly 1GB against 150MB. At this scale
# that is a slower first pull and nothing else, and it buys a build that cannot
# fail for reasons outside this repository.
FROM python:3.11

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./

# app/main.py serves this directory when index.html is present, with a history
# fallback so client-side routes survive a refresh.
COPY --from=web /web/dist ./static

# Railway injects PORT; the default keeps `docker run` usable locally.
# --no-proxy-headers is deliberate. Uvicorn rewrites request.client from
# X-Forwarded-For by default, taking the LEFTMOST entry - the one a caller can
# forge. The rate limiter needs the opposite (see client_ip in
# app/core/ratelimit.py), so uvicorn is told to leave the request alone and the
# header is interpreted in one place, with TRUSTED_PROXY_COUNT saying how many
# hops to trust.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-proxy-headers"]
