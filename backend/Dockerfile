# Why a Dockerfile rather than Railway's Nixpacks builder:
#
# SQLAlchemy's async engine routes every query through greenlet, whose compiled
# extension links against libstdc++.so.6. The Nix-based build produced an image
# where that shared object wasn't on the loader path, so the app booted and
# served /health happily but raised
#
#   ValueError: the greenlet library is required to use this function.
#   libstdc++.so.6: cannot open shared object file
#
# on the first database call - and on `alembic upgrade head`, so migrations
# couldn't run either. Pinning a Debian-based image makes the C runtime
# predictable instead of something we rediscover per deploy.

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

# Copied first so dependency layers cache across code-only changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway injects PORT; the default keeps `docker run` usable locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
