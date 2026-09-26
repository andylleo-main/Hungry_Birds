# Hunger Birds

Campus food ordering for BIT Mesra. Students browse the food stalls on campus,
place cash-on-delivery orders, and watch the status update live; stall owners
manage their menu and work through incoming orders from a separate app.

- **Customer app** (Flutter) — browse stalls, order, track live
- **Merchant app** (Flutter) — stall dashboard, live order queue, menu management
- **Backend** (FastAPI + Postgres + Redis) — API, auth, realtime

Sign-up is restricted to `@bitmesra.ac.in` email addresses. Payment is cash
only — there is no payment gateway.

## Repository layout

```
backend/               FastAPI service (API, auth, WebSockets)
apps/customer_app/     Flutter app for students
apps/merchant_app/     Flutter app for stall owners
packages/hb_shared/    Shared Dart: models, API client, login flow, theme
```

## How it works

**Auth.** A student enters their institute email; the backend generates a
6-digit code, stores it in Redis with a 5-minute TTL, and emails it through
Resend. Verifying the code issues a JWT access/refresh pair. Only
`@bitmesra.ac.in` addresses are accepted, and `+tag` addressing is normalised
away (`me+1@…` and `me@…` are the same account) so one person can't spin up
unlimited accounts.

**Vendors.** Anyone can apply to run a stall, but the stall stays invisible to
students until an admin approves it. Approved stalls also carry an
open/closed switch the owner controls from their app.

**Orders.** A cart holds items from one stall. Placing an order snapshots each
item's name and price, so later menu edits never rewrite order history. Status
moves through an explicit state machine — `placed → accepted → preparing →
ready → completed`, with `rejected`/`cancelled` as terminal branches — and
invalid jumps are rejected by the API.

**Realtime.** Every status change publishes to Redis pub/sub. The customer's
tracking screen subscribes to `order:{id}` and the merchant's queue to
`vendor:{id}`, so both sides update within a second without polling. Clients
re-fetch on reconnect, so nothing is lost if a socket drops.

## Running the backend locally

Requires Python 3.11+, Postgres and Redis.

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then edit DATABASE_URL / JWT_SECRET
alembic upgrade head
PYTHONPATH=. python scripts/seed.py    # optional: demo stalls + admin user

uvicorn app.main:app --reload
```

With `OTP_DEBUG_ECHO=true` (the default in `.env.example`) the login endpoint
returns the OTP in its response, so you can sign in locally without a Resend
key. **Keep it `false` in production** — it would otherwise let anyone log in
as any address.

To make a user an admin, have them log in once, then:

```bash
PYTHONPATH=. python scripts/promote_admin.py you@bitmesra.ac.in
```

## Running the apps

```bash
cd apps/customer_app     # or apps/merchant_app
flutter pub get
flutter run --dart-define=API_BASE_URL=http://localhost:8000
```

Point `API_BASE_URL` at the deployed URL to run against production. On an
Android emulator, localhost on the host machine is `http://10.0.2.2:8000`.

Tests: `flutter test` in either app, `flutter analyze` for lints.

## Building installable APKs

Sideloading is the practical way to get these onto phones on campus — no Play
Store account needed. Android only; iOS requires a $99/yr Apple Developer
account even for TestFlight.

### One-time: create a release keystore

Do this once, on your own machine. The same keystore signs **both** apps.

```bash
keytool -genkey -v -keystore ~/hungerbirds-release.jks \
  -keyalg RSA -keysize 2048 -validity 10000 -alias hungerbirds
```

Then, in **each** app, copy `android/key.properties.example` to
`android/key.properties` and fill in the password, alias, and absolute path to
the `.jks`. Both files are gitignored and must stay that way.

> **Back up the `.jks` file and its passwords somewhere permanent.** Android
> identifies an app by its signing key. If you lose the keystore, you cannot
> ship an update to an already-installed app — every user has to uninstall and
> reinstall, losing their login. There is no recovery path.

Without `key.properties`, release builds silently fall back to the debug key.
That's fine for `flutter run --release` on your own device, but never hand out
a debug-signed APK: the debug key differs per machine, so the same
uninstall/reinstall trap applies.

### Build

```bash
cd apps/customer_app     # then repeat for apps/merchant_app
flutter build apk --release --split-per-abi \
  --dart-define=API_BASE_URL=https://<your-service>.up.railway.app
```

Output lands in `build/app/outputs/flutter-apk/`. Hand out
**`app-arm64-v8a-release.apk`** — essentially every phone from the last several
years is arm64. `--split-per-abi` keeps it ~10–15MB instead of one ~40MB fat
APK.

Confirm it's signed with your release key, not the debug key:

```bash
apksigner verify --print-certs build/app/outputs/flutter-apk/app-arm64-v8a-release.apk
```

Recipients need to allow "install from unknown sources" when opening the file.

## Deployment (Railway)

Build, start, migrations and healthcheck all come from `backend/railway.json`,
so the only thing you set by hand is the root directory.

The backend builds from `backend/Dockerfile`. It started on Railway's Nixpacks
builder, but that produced an image missing `libstdc++.so.6` — which greenlet's
compiled extension links against, and SQLAlchemy's async engine routes every
query through greenlet. The result was an app that booted, passed `/health`,
and then failed on its first database call while `alembic upgrade head` failed
the same way. Pinning `python:3.11-slim` makes the C runtime predictable rather
than something rediscovered per deploy. You don't need Docker installed —
Railway builds the image.

### Deploying to a fresh Railway account

1. **New Project** → **Empty Project**.
2. **+ New** → **Database** → **Add PostgreSQL**.
3. **+ New** → **Database** → **Add Redis**.
4. **+ New** → **GitHub Repo** → pick this repo.
5. On that service: **Settings** → **Root Directory** → `backend`.
   Everything else is read from `backend/railway.json`. *This is the one
   setting that can't configure itself — without it the build sees the Flutter
   apps too and fails.*
6. **Variables** → add the table below.
7. **Settings** → **Networking** → **Generate Domain**.

The first deploy runs migrations before booting, then has to pass
`/health/ready` — which queries Postgres *and* pings Redis — so a green deploy
is itself proof both databases are wired up correctly.

Migrations run as `alembic upgrade head`. The Docker image installs packages
with pip into `/usr/local`, which is on PATH, so this works both as the
pre-deploy step and in the service's **Console** tab:

```bash
alembic current      # which revision is applied
alembic upgrade head # apply the rest
```

If you ever see `alembic: command not found` in the Console, you're on a
Nixpacks-built image rather than this Dockerfile — there the virtualenv lives
at `/opt/venv` and isn't on the shell's PATH, so use
`/opt/venv/bin/alembic` instead.

`/health/ready` does **not** catch a missed migration — it only runs a trivial
query, so it passes against an out-of-date schema while every real query
against `users` fails with *column users.phone does not exist*.

### Variables

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` — a Railway **reference**, not a pasted URL |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` — likewise |
| `JWT_SECRET` | long random string: `openssl rand -hex 32` |
| `RESEND_API_KEY` | from the Resend dashboard |
| `RESEND_FROM_EMAIL` | `Hunger Birds <noreply@yourdomain>` — the domain must be verified in Resend |
| `CLOUDINARY_CLOUD_NAME` | optional; photos are disabled until all three are set |
| `CLOUDINARY_API_KEY` | optional |
| `CLOUDINARY_API_SECRET` | optional |

`ALLOWED_EMAIL_DOMAIN` (`bitmesra.ac.in`), `OTP_DEBUG_ECHO` (`false`) and
`CORS_ORIGINS` (`*`) already default correctly — you only need to set them to
change them.

> **Never set `OTP_DEBUG_ECHO=true` on a public URL.** It returns the login
> code in the API response, which lets anyone sign in as anyone. It exists so
> you can log in locally without a Resend account.

If Postgres and Redis are referenced correctly, a plain `postgres://` URL is
upgraded to the asyncpg driver automatically — you don't need to rewrite it.

### Seeding

Once deployed, from the service's shell:

```bash
PYTHONPATH=. python scripts/seed.py
```

Creates the `admin@bitmesra.ac.in` admin plus three demo stalls. It's
idempotent (skips stalls that already exist) and deliberately *not* part of the
deploy, so it can't resurrect demo stalls you've deleted. Log in as that
address in either app to get admin access, then approve real vendors.

### Pointing the apps at it

```bash
flutter run --dart-define=API_BASE_URL=https://<your-service>.up.railway.app
```

Images upload straight from the phone to Cloudinary using a short-lived
signature minted by `GET /media/signature`, so image bytes never pass through
the backend.

## Things to know before going live

- **Resend needs a verified domain of its own** before it will deliver to real
  `@bitmesra.ac.in` inboxes. Until then OTP emails only reach your own Resend
  account address, so nobody else can log in. Note you can't verify
  `bitmesra.ac.in` itself — that's the institute's DNS — so register any cheap
  domain, verify it in Resend, and send from it. Sending *to* institute
  addresses is unaffected. DNS propagation is the slow part; start it early.
- **Customers must add a phone number** before their first order — the backend
  rejects an order without one, and the app prompts for it at checkout. It's
  how a stall calls about a ready order, since everything is cash on pickup.
- **Distributing the apps** is not covered here. Android can be sideloaded as
  an APK; iOS requires an Apple Developer account ($99/yr) even for TestFlight.
- **No ratings or reviews** — deliberately out of scope for the first version.
