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
FROM python:3.11-slim

# greenlet's wheel needs the C++ runtime. Installed explicitly so this doesn't
# silently depend on whatever the base image happens to ship.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

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
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
