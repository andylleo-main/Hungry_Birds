# Hungry Birds

Campus food ordering for BIT Mesra: students order from stalls in a web app,
stall owners work the queue in an Android app, their riders deliver with a third.

## Naming

The product is **Hungry Birds** — "hungry", never "hunger". There is no such
thing as "Hunger Birds".

The old misspelling survives on purpose in exactly these places, and nowhere
else. A `grep -i hunger` turning up anything beyond this list is a bug:

- The `applicationId` history comments in both apps'
  `android/app/build.gradle.kts`, which record `food.hungerbirds.*` as real
  identifiers that really shipped in a build. Rewriting a changelog to pretend
  the mistake never happened makes the warning it carries incomprehensible.
- The explanation of all this in README.md, and this section.
- A dead `food.hungerbirds.merchant` client inside both apps'
  `android/app/google-services.json`, left over from the registration made before
  the rename. The Gradle plugin matches on `applicationId` and ignores the rest,
  so it costs nothing; deleting that app in the Firebase console and
  re-downloading is the tidy-up.

The git repository and its clone directory are `Hunger_Birds`. Renaming a GitHub
repository is the user's call, not something to do while fixing strings.

Identifiers in use: Android `food.hungrybirds.merchant` / `food.hungrybirds.rider`,
Dart packages `hb_shared`, Firebase project `hungrybirds-7779f`.

## Standing instructions from the user

- **Do not mix this project with Knitcult or Laoni.** Different products. Do not
  copy code, config or conventions between them. Cashfree is the one deliberate
  exception: the user asked for the same SDK integration Knitcult uses.
- **No purple anywhere** in any UI.
- **Another session works in this repo.** Fetch before committing, keep commits
  scoped, never force-push a shared branch.
- Merchants cannot do their work in the web app. Android only.
- No cash on delivery. Every order is paid up front through Cashfree.

## Secrets

Never paste a credential into a transcript, and never commit one. Firebase
service account keys, Cashfree secrets, the Resend key and the Cloudinary secret
all live in Railway variables and in a gitignored local `.env`.

`google-services.json` is **not** a secret — it ships inside every APK — and is
committed on purpose.

`OTP_DEBUG_ECHO` must never be true on a public URL. It is double-gated behind
`ENVIRONMENT=development`; leave both gates in place.

## Layout

| Path | What |
| --- | --- |
| `backend/` | FastAPI, SQLAlchemy async, Alembic, Redis |
| `apps/web/` | React + Vite customer app, and the embedded admin panel |
| `apps/merchant_app/` | Flutter Android app for stall owners |
| `apps/rider_app/` | Flutter Android app for riders |
| `packages/hb_shared/` | Dart code shared by the two Flutter apps |

There is no customer Flutter app. It was deleted once the web app took over; its
history is in git if it is ever wanted back.
