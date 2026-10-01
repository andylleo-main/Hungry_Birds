# Hungry Birds

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
Resend. Verifying the code issues an access token and an opaque, revocable
refresh token. Customers must use an `@bitmesra.ac.in` address, and `+tag`
addressing is normalised away (`me+1@…` and `me@…` are the same account) so one
person can't spin up unlimited accounts. Stall owners sign in on their own routes
with any address — see [Who signs in where](#who-signs-in-where).

**Vendors.** Anyone can sign up to run a stall, but the stall stays invisible to
students until an admin approves it. Approved stalls carry an open/closed switch
the owner controls from their app, plus the dine-in and delivery settings in
[How a stall serves](#how-a-stall-serves).

**Orders.** A cart holds items from one stall. Placing an order snapshots each
item's name and price, so later menu edits never rewrite order history. Each
order is either dine-in or a delivery to one campus location, checked against
what that stall currently offers. Status moves through an explicit state machine
— `placed → accepted → preparing → ready → completed`, with
`rejected`/`cancelled` as terminal branches — and invalid jumps are rejected by
the API.

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

uvicorn app.main:app --reload --no-proxy-headers
```

`.env.example` sets `ENVIRONMENT=development`, which unlocks two local
conveniences: `OTP_DEBUG_ECHO=true` makes the login endpoint return the OTP in
its response, so you can sign in without a Resend key, and CORS is opened to
Vite's ports so the web app can call the API across origins. Both are inert
without `ENVIRONMENT=development`, so neither can be switched on in production
by setting a single variable.

It also sets `TRUSTED_PROXY_COUNT=0`, because nothing sits in front of the app
locally. Combined with `--no-proxy-headers` above, that means `X-Forwarded-For`
is ignored entirely and rate limits key off the real connection — matching how
production behaves behind Railway's one proxy.

To make a user an admin, have them log in once, then:

```bash
PYTHONPATH=. python scripts/promote_admin.py you@bitmesra.ac.in
```

## Running the apps

```bash
cd apps/merchant_app
flutter pub get
flutter run --dart-define=API_BASE_URL=http://localhost:8000/api
```

Point `API_BASE_URL` at the deployed URL to run against production — note the
`/api` suffix. On an Android emulator, localhost on the host machine is
`http://10.0.2.2:8000/api`.

> `apps/customer_app` is the retired Flutter customer app. The customer side is
> now the web app in `apps/web`; that directory is kept only as history.

### The customer web app

```bash
cd apps/web
npm install
VITE_API_BASE_URL=http://localhost:8000/api npm run dev
```

In production no such variable is set: the API is same-origin under `/api`, so
the deployed hostname never has to be baked into the bundle.

Tests: `flutter test` in either app, `flutter analyze` for lints.

## Building installable APKs

Sideloading is the practical way to get these onto phones on campus — no Play
Store account needed. Android only; iOS requires a $99/yr Apple Developer
account even for TestFlight.

### One-time: create a release keystore

Do this once, on your own machine. The same keystore signs **all three** apps.

```bash
keytool -genkey -v -keystore ~/hungerbirds-release.jks \
  -keyalg RSA -keysize 2048 -validity 10000 -alias hungerbirds
```

Then, in **each** app (`merchant_app`, `rider_app`, and `customer_app` if you
still build it), copy `android/key.properties.example` to
`android/key.properties` and fill in the password, alias, and absolute path to
the `.jks`. Those files are gitignored and must stay that way.

> **Back up the `.jks` file and its passwords somewhere permanent.** Android
> identifies an app by its signing key. If you lose the keystore, you cannot
> ship an update to an already-installed app — every user has to uninstall and
> reinstall, losing their login. There is no recovery path.

Without `key.properties`, release builds silently fall back to the debug key.
That's fine for `flutter run --release` on your own device, but never hand out
a debug-signed APK: the debug key differs per machine, so the same
uninstall/reinstall trap applies.

### Build

Same command for each app — `merchant_app` for stall owners, `rider_app` for
the people who carry the deliveries:

```bash
cd apps/merchant_app        # or apps/rider_app
flutter build apk --release --split-per-abi \
  --dart-define=API_BASE_URL=https://<your-service>.up.railway.app/api
```

They are separate apps with separate package ids
(`food.hungerbirds.merchant`, `food.hungerbirds.rider`), so a merchant who also
rides can have both installed at once.

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

Build, start, migrations and healthcheck all come from `railway.json` at the
repo root.

**One service serves everything.** The Docker build compiles the customer web
app and the API copies the result into `backend/static`, serving it alongside
the API on the same origin. That means one Railway service instead of two (half
the cost), no CORS to configure, and no deployed hostname baked into the
frontend bundle at build time.

The API lives under **`/api`**, which is load-bearing rather than cosmetic:
without it the API's `GET /orders/{id}` shadows the web app's `/orders/:id`
tracking route, and refreshing that page returns JSON instead of the page.
`/health` and `/health/ready` stay at the root for the deploy healthcheck.

The backend builds from `backend/Dockerfile`. It started on Railway's Nixpacks
builder, but that produced an image missing `libstdc++.so.6` — which greenlet's
compiled extension links against, and SQLAlchemy's async engine routes every
query through greenlet. The result was an app that booted, passed `/health`,
and then failed on its first database call while `alembic upgrade head` failed
the same way. Pinning a Debian base makes the C runtime predictable rather
than something rediscovered per deploy.

The slim build compiles Python and then purges its build dependencies, and the
C++ runtime goes with them — so the Dockerfile installs `libstdc++6` back
explicitly. That step was once blamed for a failed build and the image was
moved to the full `python:3.11` to avoid it; the diagnosis was wrong (see the
Root Directory note above) and it has since been moved back, because slim is
~150MB against ~1GB. You don't need Docker installed —
Railway builds the image.

### Deploying to a fresh Railway account

1. **New Project** → **Empty Project**.
2. **+ New** → **Database** → **Add PostgreSQL**.
3. **+ New** → **Database** → **Add Redis**.
4. **+ New** → **GitHub Repo** → pick this repo.
5. On that service: **Settings** → **Root Directory** → leave it **empty**
   (the repo root). The Docker build needs both `backend/` and `apps/web/`, so
   the context has to be the whole repo. Everything else is read from
   `railway.json`. *If you previously set this to `backend`, clear it — with
   it set the build can't see `apps/web` and fails.*

   > **How this failure looks, because it is not obvious.** The build dies in
   > about three seconds, and the step it blames is whatever happened to be
   > running in the *other* stage — an `apt-get`, a `pip install` — not the
   > `COPY apps/web/...` that actually failed. BuildKit runs both stages of
   > this Dockerfile in parallel and cancels everything in flight when one
   > dies, so a cancelled step gets reported as a failed one. If a build fails
   > in a few seconds and the named step looks unrelated to anything you
   > changed, check Root Directory before believing the error. Railway's
   > **Diagnose** button identifies this correctly.
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
| `RESEND_FROM_EMAIL` | `Hungry Birds <noreply@yourdomain>` — the domain must be verified in Resend |
| `CLOUDINARY_CLOUD_NAME` | optional; photos are disabled until all three are set |
| `CLOUDINARY_API_KEY` | optional |
| `CLOUDINARY_API_SECRET` | optional |
| `CORS_ORIGINS` | your own domain, e.g. `https://hungerbirds.food`. Leave unset for none at all — correct when the backend serves the web app, which it does |

Everything else defaults safely and only needs setting to change it:
`ALLOWED_EMAIL_DOMAIN` (`bitmesra.ac.in`), `ENVIRONMENT` (`production`),
`OTP_DEBUG_ECHO` (`false`), `TRUSTED_PROXY_COUNT` (`1`, which is right for
Railway), `MAX_REQUEST_BYTES` (256 KB) and the two `GLOBAL_RATE_LIMIT_*`
values.

> **Never set `OTP_DEBUG_ECHO=true` on a public URL.** It returns the login
> code in the API response, which lets anyone sign in as anyone. It exists so
> you can log in locally without a Resend account. As a second line of defence
> it is ignored unless `ENVIRONMENT=development` as well, so copying it into
> Railway by accident does nothing — but don't rely on that.

> **Don't change `TRUSTED_PROXY_COUNT` unless the number of proxies in front of
> the app changes.** It says how far into `X-Forwarded-For` to look for the real
> client address. Setting it higher than the true number of hops lets a caller
> forge that address and get a fresh rate-limit budget on every request, which
> disables the per-IP limits. Railway is exactly one hop.

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
flutter run --dart-define=API_BASE_URL=https://<your-service>.up.railway.app/api
```

Images upload straight from the phone to Cloudinary using a short-lived
signature minted by `GET /media/signature`, so image bytes never pass through
the backend.

## Who signs in where

Three apps share one API, and each has a different rule about who may hold an
account.

| Who | Where they sign in | Address | Route |
| --- | --- | --- | --- |
| Customers | the web app | `@bitmesra.ac.in` only | `POST /api/auth/otp/{request,verify}` |
| Stall owners | the Android merchant app | any email | `POST /api/auth/vendor/otp/{request,verify}` |
| Admins | the web app | their institute address | `POST /api/auth/admin/login` |

A stall's address does not have to be an institute one - a stall is a business.
An account's role is set when it is created and nothing changes it afterwards,
so somebody who is both a student and a stall owner needs two addresses. That is
deliberate: role decides whether an account can spend money on campus or sell
food to it, and a role a later request can flip is not a boundary.

Access tokens carry an audience (`web`, `merchant`), so a session belonging to
one app cannot be replayed against another's endpoints.

**What that does and does not enforce**, because the difference matters:

- *Enforced.* Only an institute address can place an order. It is checked both by
  role - a vendor account is not a customer account - and by re-checking the
  domain at the point of ordering, so it holds regardless of how accounts come
  to exist later.
- *Enforced.* A stall is invisible to customers and cannot receive an order until
  an admin approves it.
- *Not enforced, and not claimed to be.* "Stall owners only work in the Android
  app." The API is public and there is no client attestation, so nothing stops
  someone calling the vendor routes with curl. What is true is narrower and
  enough: the web app contains no vendor screens at all, and a vendor account
  cannot order. The audience check buys session separation, not proof of client.

The residual worth knowing: the vendor signup route will email any address on the
internet, which makes it a relay someone could point at a stranger. It is capped
hard per IP (three a minute, ten an hour) and per address, not prevented. If it
is ever abused, the fix is invite-only stalls - an admin creates the account and
the vendor signs in to an existing row.

## How a stall serves

Each stall chooses, in the merchant app under **Your stall → How you serve**:

- **Dine in** on or off - eat at, or collect from, the counter.
- **Delivery** on or off, and which of the eighteen campus locations it carries
  to: Hostels 1-13, RS Hostel, R&D Building, Biotech Department, Lecture Hall 1,
  IC Arena.

Everywhere is on by default, including for stalls that existed before delivery
did. Only the locations a stall switches *off* are stored, which is what makes
that true without seeding anything. Customers are offered only the places a stall
keeps on, and an order naming any other is refused. A stall cannot switch both
dine-in and delivery off - that would read as open while rejecting everything, and
there is already a switch for being closed.

## Riders

Riders belong to the stall, not to the platform. A merchant hires and manages
their own from the merchant app; there is deliberately no admin route for
creating one.

**Credentials.** The merchant adds a rider with a name and a phone number, and
the server generates a login id and a readable password (`swift-mango-4218`).
That password is shown once, in the response that creates it, and stored only as
an scrypt hash. Whenever the merchant needs it again they press **Regenerate**,
which issues a new one and shows that.

This is the answer to "the merchant needs to be able to see the password" without
a recoverable copy sitting in the database. The merchant can always produce a
working password for any rider; nothing in a database backup yields one. It also
makes the obvious safety property true: regenerating bumps a credential version
carried inside the rider's token, so the moment a merchant regenerates - or
switches a rider off - that rider's phone is signed out. Without that, a rider who
had quit would keep a working token until it expired and the button would be
theatre.

Passwords are readable on purpose. One gets read aloud or written on a slip and
typed into a phone one-handed; a random string of symbols gets copied down wrong,
and the workaround for that is a whole stall sharing one password. The trade is
that they carry about 34 bits, so rider sign-in is rate limited hard per IP (five
a minute, thirty an hour) and fails closed if Redis is unreachable.

**Riders are not a fourth user role.** They live in their own `riders` table with
their own token type. That is partly because they sign in with an id rather than
an email, partly because a rider belongs to exactly one stall, and mostly because
a new `UserRole` value would fail *open*: plenty of endpoints accept any
authenticated user, so a new role silently gains access everywhere nobody thought
about roles. A separate table fails closed - a rider is not a `User`, so every
existing endpoint rejects a rider token without a line of change.

**Assignment.** For a delivery order the merchant either assigns a rider or
marks it as one they will take themselves. Assigning is what exchanges phone
numbers: the rider's app shows the customer's number, and the customer's tracking
page gains a **Call rider** button. Neither number is visible before assignment,
and taking an order back off a rider removes their number from the customer's view
again. Assignment does not move the order's status - a merchant usually assigns
while the food is still cooking, and jumping to "out for delivery" would tell the
customer it had left before it had.

The rider then marks the order picked up (`out_for_delivery`) and delivered
(`completed`). Those two are the only statuses a rider may set; accepting,
rejecting and cooking stay the stall's to say. `out_for_delivery` is refused on a
dine-in order.

The rider app polls its order list rather than holding a WebSocket. A rider
carries one or two orders at a time, so a short poll of one small query costs less
than giving a third audience its own ticket-and-socket path, and it cannot get
wedged in a way that quietly stops delivering updates.

## Admin sign-in without an OTP

Admins can sign in with a password instead of waiting for a code. That matters
because the admin is exactly the account you need when email is the thing that
has broken, and a code you cannot receive is a bad way to be locked out of your
own service.

Set it up once, from `backend/`:

```bash
PYTHONPATH=. python scripts/set_admin_password.py
```

It prompts without echoing and prints a hash. Put that in Railway as
`ADMIN_PASSWORD_HASH`. The password itself is never stored anywhere and cannot
be recovered from the hash, so keep it in a password manager.

The login page then offers **Admin sign-in** beneath the normal form.

It is a second way in, so it is built like one:

- **Off unless configured.** With `ADMIN_PASSWORD_HASH` empty the endpoint
  returns 404 — the door does not exist rather than standing locked.
- **The role is what grants access, not the password.** A customer who somehow
  learned the password still gets 401; only an account already holding the
  admin role can use it.
- **One message for every failure.** Unknown address, non-admin account and
  wrong password all return the same 401, and an unknown address spends the
  same time as a real check, so nobody can map which addresses are admins
  before they start guessing.
- **Five attempts a minute, twenty an hour, per address**, and that limiter
  *fails closed* — if Redis is unreachable the endpoint refuses rather than
  becoming an unlimited guessing surface. A password is guessable in a way a
  random six-digit code with a five-minute life is not.
- Hashed with scrypt (stdlib, no new dependency), salted per password, with the
  work factor stored alongside so it can be raised later.

Nothing about the resulting session is special: it is the same rotating,
revocable session the OTP flow issues, and it appears in *Where you're signed
in* like any other device.

## Rate limiting

Every endpoint is rate limited, and the limits live in one file —
`backend/app/core/limits.py` — so they can be reviewed as a whole rather than
hunted through the routers. Each is sized by the harm it prevents:

- **Login** is limited per email address *and* per client address. The per-address
  limits stop someone working one account; the per-IP ones stop them spraying
  many, which would otherwise enumerate accounts and burn the Resend quota —
  and once that quota is spent, nobody can log in at all.
- **Orders** are capped per account, because a few hundred junk orders makes a
  stall's tablet useless during a lunch rush. That is an outage for that vendor
  even though every individual order looked legitimate.
- **Upload signatures** are capped because each one is a permit to upload to the
  Cloudinary account — unlimited permits means one user can fill the free tier
  and take image hosting down for every stall.
- **Public browsing** is capped per address; the stall detail endpoint loads a
  whole menu per call, so it is the cheapest way to put load on the database.
- **A blanket per-IP ceiling** sits under all of it, to catch a client that
  spreads abuse across many endpoints to stay below each individual limit.

Anything behind a token is counted per account rather than per address, so
switching networks doesn't reset it and the shared campus NAT doesn't punish
everyone for one person. Health checks are never throttled — a 429 there would
read as a dead service and roll back a deploy.

Two things that are easy to get wrong and are asserted by tests
(`backend/tests/test_deploy_config.py`, `backend/tests/test_ratelimit.py`):

- Uvicorn is started with **`--no-proxy-headers`**. Its default rewrites the
  client address from the *leftmost* `X-Forwarded-For` entry — the forgeable
  one. The limiter reads that header itself, from the right, trusting only
  `TRUSTED_PROXY_COUNT` hops. If uvicorn is allowed to substitute a forged value
  underneath it, every per-IP limit becomes bypassable with one header.
- The login limits **fail closed**. If Redis is unreachable they refuse requests
  rather than allowing them, because a limiter that silently stops working there
  is the whole hole; the codes live in Redis anyway, so those endpoints cannot
  work without it. Every other limit fails open, so a Redis blip doesn't take
  the app down.

## Live updates

The apps get order updates over a WebSocket. A browser can't set headers on a
WebSocket handshake, so the credential has to travel in the URL — and URLs end
up in server logs, proxy logs and browser history. The access token therefore
never goes there. The client spends it once, over a normal authenticated
request to `POST /api/realtime/ticket`, on a ticket that is valid for 30
seconds and destroyed the moment the socket redeems it. A ticket found in a log
afterwards is worthless, and it can't be replayed.

## Icons and branding

Every icon — the web favicon and touch icons, both Android apps' launcher
icons, and the Play Store listing image — is generated from one master by
`design/make_icons.py`. Re-run it after changing the artwork; it is idempotent,
so a run with no change to the master rewrites nothing.

`design/logo.svg` is the supplied artwork and is **not** used at runtime. It is
a VTracer auto-trace: 2,848 paths, 1.1MB, no viewBox, with an opaque backdrop
baked in as a full-canvas path. That is several times the size of the entire
web bundle, for a mark drawn at 40 pixels. `design/logo-master.png` is the
usable form — backdrop removed, cropped to the artwork, squared. The crop is
what makes the icon legible at 48px instead of a scattering of specks.

The Android icons are both legacy and adaptive:

- `mipmap-*/ic_launcher.png` — opaque and rounded, for Android 7 and below,
  which draws a launcher icon exactly as given. A transparent one would leave
  the bird floating with no shape behind it.
- `mipmap-anydpi-v26/ic_launcher.xml` plus `ic_launcher_foreground.png` — the
  adaptive icon used from Android 8 on. The launcher masks it to a circle,
  squircle or teardrop, so the artwork sits at 62% of the 108dp canvas, inside
  the 72dp area the system guarantees is visible.

No manifest change is needed: `@mipmap/ic_launcher` resolves to the adaptive
XML on API 26+ and to the PNGs below that.

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
