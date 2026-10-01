#!/usr/bin/env bash
#
# Build distributable release APKs for the merchant and rider apps.
#
# This exists because three things can go wrong at build time without saying so,
# each producing an APK that installs, runs, and is wrong:
#
#   1. Forgetting --dart-define=API_BASE_URL. The value is a compile-time const,
#      so it is baked into the APK - changing it later means rebuilding AND
#      reinstalling everywhere. AppConfig defaults to the live domain now, so a
#      forgotten flag no longer points the app at nothing; it is still demanded
#      below, because a default is a safety net against a silent mistake, not a
#      statement of which backend you meant to build against.
#   2. Building without android/key.properties. Gradle deliberately falls back to
#      the debug key so `flutter run --release` works on a fresh clone. For
#      anything handed to somebody else that fallback is the worst case: the debug
#      key differs per machine and is not backed up, so the app can never be
#      updated.
#   3. Handing over the wrong ABI. --split-per-abi writes three APKs and the v7a
#      one installs happily on an arm64 phone.
#
# All three are hard failures or removed outright below. Use `flutter build apk`
# directly if you want one app, unsigned, or a different ABI.
#
# Usage:
#   API_BASE_URL=https://your-host/api ./scripts/build_apks.sh
#   API_BASE_URL=... ./scripts/build_apks.sh merchant_app      # one app only

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$REPO/dist"
APPS=("${@:-}")
[[ -z "${APPS[0]}" ]] && APPS=(merchant_app rider_app)

die() { printf '\n\033[31merror:\033[0m %s\n\n' "$1" >&2; exit 1; }
note() { printf '\033[36m==>\033[0m %s\n' "$1"; }

# --- 1. the URL, which is baked in and cannot be changed after the fact --------

[[ -n "${API_BASE_URL:-}" ]] || die "API_BASE_URL is not set.

  API_BASE_URL=https://your-host/api $0

Without it the APK is compiled against http://localhost:8000/api and will reach
nothing from a phone. There is deliberately no default here: a wrong URL is only
discoverable by installing the result, so it has to be stated every time."

[[ "$API_BASE_URL" == https://* ]] || die "API_BASE_URL must be https://.
Android blocks cleartext HTTP by default, so an http:// host fails on the phone
even when the server answers. Got: $API_BASE_URL"

[[ "$API_BASE_URL" == */api ]] || die "API_BASE_URL must end in /api - every
request path is appended to it. Got: $API_BASE_URL"

# Printed loudly rather than quietly honoured. A typo'd host is the one mistake
# here that survives all the way onto somebody else's phone.
note "compiling against $API_BASE_URL"

# --- 2. signing, checked before spending minutes on a build that is useless ----

for app in "${APPS[@]}"; do
  [[ -d "$REPO/apps/$app" ]] || die "no such app: apps/$app"
  props="$REPO/apps/$app/android/key.properties"
  [[ -f "$props" ]] || die "missing $props

Copy apps/$app/android/key.properties.example to key.properties and fill it in.
Gradle would otherwise fall back to the debug key and still succeed - fine for
\`flutter run --release\` on your own device, never for an APK you hand out,
because a debug-signed app can never be updated. See README.md, \"One-time:
create a release keystore\"."
done

# --- 3. find apksigner, so signing is confirmed rather than assumed ------------

APKSIGNER="$(command -v apksigner || true)"
if [[ -z "$APKSIGNER" ]]; then
  for sdk in "${ANDROID_HOME:-}" "${ANDROID_SDK_ROOT:-}" "$HOME/Library/Android/sdk" "$HOME/Android/Sdk"; do
    [[ -n "$sdk" && -d "$sdk/build-tools" ]] || continue
    # Newest build-tools version wins; -V sorts 34.0.0 above 9.0.0 correctly.
    APKSIGNER="$(find "$sdk/build-tools" -maxdepth 2 -name apksigner -type f 2>/dev/null | sort -V | tail -1)"
    [[ -n "$APKSIGNER" ]] && break
  done
fi

# --- build ---------------------------------------------------------------------

mkdir -p "$DIST"

for app in "${APPS[@]}"; do
  note "building $app"
  cd "$REPO/apps/$app"

  # The Kotlin package moved during the hungerbirds -> hungrybirds rename, and
  # Gradle's incremental state keeps generated sources under the old name. Cheap
  # insurance against a confusing failure.
  flutter clean >/dev/null
  flutter pub get >/dev/null

  flutter build apk --release --split-per-abi \
    --dart-define=API_BASE_URL="$API_BASE_URL"

  apk="build/app/outputs/flutter-apk/app-arm64-v8a-release.apk"
  [[ -f "$apk" ]] || die "expected $apk but it is not there"

  version="$(sed -n 's/^version: *\([0-9.]*\).*/\1/p' pubspec.yaml)"
  out="$DIST/hungrybirds-${app%_app}-${version:-unknown}-arm64.apk"
  cp "$apk" "$out"

  if [[ -n "$APKSIGNER" ]]; then
    note "signature of $(basename "$out")"
    # Grepped rather than dumped: the full output is a dozen lines of digests and
    # the only question being asked is whose key signed it.
    "$APKSIGNER" verify --print-certs "$out" | grep -i "certificate DN" || true
    if "$APKSIGNER" verify --print-certs "$out" | grep -qi "CN=Android Debug"; then
      die "$(basename "$out") is DEBUG-SIGNED despite key.properties being present.
Check that storeFile, keyAlias and both passwords in
apps/$app/android/key.properties match what is actually inside the .jks.
Do not distribute this file: a debug-signed app can never be updated."
    fi
  else
    printf '\033[33mwarning:\033[0m apksigner not found, signature unverified.\n'
    printf '         It lives in the Android SDK under build-tools/. Set\n'
    printf '         ANDROID_HOME, or run: apksigner verify --print-certs %s\n' "$out"
  fi
done

note "done"
printf '\n'
ls -lh "$DIST"/*.apk
printf '\nHand out the files above. Each is arm64-only, which covers essentially\n'
printf 'every phone from the last several years.\n'
