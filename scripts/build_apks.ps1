<#
.SYNOPSIS
    Build distributable release APKs for the merchant and rider apps.

.DESCRIPTION
    The PowerShell twin of scripts/build_apks.sh, for Windows without Git Bash.
    Same guards, because the three mistakes they catch are invisible at build
    time and each produces an APK that installs, runs, and is wrong:

      1. Forgetting the backend URL. It is a compile-time constant baked into
         the APK, so changing it later means rebuilding AND reinstalling
         everywhere. -Live names the production deployment; -ApiBaseUrl takes
         any other. One of the two is required - there is deliberately no
         silent default, because a wrong host is only discoverable by
         installing the result.
      2. Building without android\key.properties. Gradle falls back to the
         debug key so `flutter run --release` works on a fresh clone, and
         succeeds. For anything handed to somebody else that is the worst
         case: the debug key differs per machine and is not backed up, so the
         app can never be updated.
      3. Handing over the wrong ABI. --split-per-abi writes three APKs and the
         armeabi-v7a one installs happily on an arm64 phone.

.EXAMPLE
    .\scripts\build_apks.ps1 -Live

.EXAMPLE
    .\scripts\build_apks.ps1 -ApiBaseUrl https://staging.example.com/api rider_app
#>

# PositionalBinding=$false so a bare app name cannot land in -ApiBaseUrl.
# Without it, `build_apks.ps1 -Live rider_app` bound "rider_app" as the URL and
# failed complaining that -Live and -ApiBaseUrl disagreed, naming an argument
# the caller never passed.
[CmdletBinding(PositionalBinding = $false)]
param(
    # The deployment students use.
    [switch]$Live,

    # Any other backend. Must be https and end in /api.
    [string]$ApiBaseUrl,

    # Which apps to build. Both, if not given.
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Apps
)

$ErrorActionPreference = 'Stop'

$LIVE_API_BASE_URL = 'https://www.hungrybirds.food/api'

$repo = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $repo 'dist'

function Write-Note($message) { Write-Host "==> $message" -ForegroundColor Cyan }

function Stop-Build($message) {
    Write-Host ''
    Write-Host 'error: ' -ForegroundColor Red -NoNewline
    Write-Host $message
    Write-Host ''
    exit 1
}

if (-not $Apps -or $Apps.Count -eq 0) { $Apps = @('merchant_app', 'rider_app') }

# --- 1. the URL, which is baked in and cannot be changed after the fact -------

if ($Live) {
    if ($ApiBaseUrl -and $ApiBaseUrl -ne $LIVE_API_BASE_URL) {
        Stop-Build "-Live and -ApiBaseUrl disagree. Pass one.`n`n  -Live       $LIVE_API_BASE_URL`n  -ApiBaseUrl $ApiBaseUrl"
    }
    $ApiBaseUrl = $LIVE_API_BASE_URL
}

if (-not $ApiBaseUrl) {
    Stop-Build @"
no backend chosen.

  .\scripts\build_apks.ps1 -Live                                  # $LIVE_API_BASE_URL
  .\scripts\build_apks.ps1 -ApiBaseUrl https://your-host/api      # anything else

The host is a compile-time constant, baked into the APK: changing it later means
rebuilding AND reinstalling everywhere. There is deliberately no silent default,
because a wrong one is only discoverable by installing the result.
"@
}

if (-not $ApiBaseUrl.StartsWith('https://')) {
    Stop-Build "the API base URL must be https://.`nAndroid blocks cleartext HTTP by default, so an http:// host fails on the phone`neven when the server answers. Got: $ApiBaseUrl"
}

if (-not $ApiBaseUrl.EndsWith('/api')) {
    Stop-Build "the API base URL must end in /api - every request path is appended`nto it. Got: $ApiBaseUrl"
}

# Printed loudly rather than quietly honoured. A typo'd host is the one mistake
# here that survives all the way onto somebody else's phone.
Write-Note "compiling against $ApiBaseUrl"

# --- 2. signing, checked before spending minutes on a build that is useless ---

foreach ($app in $Apps) {
    $appDir = Join-Path $repo "apps\$app"
    if (-not (Test-Path $appDir)) { Stop-Build "no such app: apps\$app" }

    $props = Join-Path $appDir 'android\key.properties'
    if (-not (Test-Path $props)) {
        Stop-Build @"
missing $props

Copy apps\$app\android\key.properties.example to key.properties and fill it in.
Gradle would otherwise fall back to the debug key and still succeed - fine for
``flutter run --release`` on your own device, never for an APK you hand out,
because a debug-signed app can never be updated. See README.md, "One-time:
create a release keystore".
"@
    }
}

# --- 3. find apksigner, so signing is confirmed rather than assumed ----------

# Written without ?. and ?? on purpose: those are PowerShell 7 only, and this
# has to run on the Windows PowerShell 5.1 that ships with Windows, where they
# are a parse error - the script would not start at all.
$apksigner = $null
$onPath = Get-Command apksigner.bat -ErrorAction SilentlyContinue
if ($onPath) { $apksigner = $onPath.Source }

if (-not $apksigner) {
    # Each Join-Path is guarded because Join-Path throws on a null Path rather
    # than returning nothing. These two are always set on Windows, but a null
    # here would take the whole script down before the first build.
    $roots = @()
    foreach ($explicit in $env:ANDROID_HOME, $env:ANDROID_SDK_ROOT) {
        if ($explicit) { $roots += $explicit }
    }
    if ($env:LOCALAPPDATA) { $roots += (Join-Path $env:LOCALAPPDATA 'Android\Sdk') }
    if ($env:USERPROFILE) { $roots += (Join-Path $env:USERPROFILE 'AppData\Local\Android\Sdk') }

    foreach ($root in $roots) {
        $buildTools = Join-Path $root 'build-tools'
        if (-not (Test-Path $buildTools)) { continue }
        # Newest build-tools wins. Sorted as versions, so 36.0.0 beats 9.0.0 -
        # a plain string sort would not.
        $apksigner = Get-ChildItem $buildTools -Filter 'apksigner.bat' -Recurse -ErrorAction SilentlyContinue |
            Sort-Object { try { [version]$_.Directory.Name } catch { [version]'0.0.0' } } |
            Select-Object -Last 1 -ExpandProperty FullName
        if ($apksigner) { break }
    }
}

# --- build -------------------------------------------------------------------

New-Item -ItemType Directory -Force -Path $dist | Out-Null

foreach ($app in $Apps) {
    Write-Note "building $app"
    $appDir = Join-Path $repo "apps\$app"
    Push-Location $appDir
    try {
        # The Kotlin package moved during the hungerbirds -> hungrybirds rename,
        # and Gradle's incremental state keeps generated sources under the old
        # name. Cheap insurance against a confusing failure.
        flutter clean | Out-Null
        flutter pub get | Out-Null

        # Read before building, not after: it is compiled in, so that the app
        # can show which build it is. A bug report against the wrong APK wastes
        # a whole round, and this is what stops that being guesswork.
        $fullVersion = (Select-String -Path 'pubspec.yaml' -Pattern '^version:\s*(\S+)' |
            Select-Object -First 1).Matches.Groups[1].Value
        if (-not $fullVersion) { $fullVersion = 'unknown' }
        Write-Note "$app $fullVersion"

        flutter build apk --release --split-per-abi `
            "--dart-define=API_BASE_URL=$ApiBaseUrl" `
            "--dart-define=APP_VERSION=$fullVersion"
        if ($LASTEXITCODE -ne 0) { Stop-Build "flutter build apk failed for $app (exit $LASTEXITCODE)" }

        $apk = 'build\app\outputs\flutter-apk\app-arm64-v8a-release.apk'
        if (-not (Test-Path $apk)) { Stop-Build "expected $apk but it is not there" }

        $version = (Select-String -Path 'pubspec.yaml' -Pattern '^version:\s*([0-9.]+)' |
            Select-Object -First 1).Matches.Groups[1].Value
        if (-not $version) { $version = 'unknown' }

        $name = "hungrybirds-$($app -replace '_app$','')-$version-arm64.apk"
        $out = Join-Path $dist $name
        Copy-Item $apk $out -Force

        if ($apksigner) {
            Write-Note "signature of $name"
            $certs = & $apksigner verify --print-certs $out 2>&1
            # Grepped rather than dumped: the full output is a dozen lines of
            # digests and the only question being asked is whose key signed it.
            $certs | Select-String 'certificate DN' | ForEach-Object { Write-Host $_.Line }
            if ($certs | Select-String 'CN=Android Debug') {
                Stop-Build @"
$name is DEBUG-SIGNED despite key.properties being present.
Check that storeFile, keyAlias and both passwords in
apps\$app\android\key.properties match what is actually inside the .jks.

On Windows, storeFile needs FORWARD slashes - it is a Java .properties file,
where a backslash is an escape character, so C:\Users\you\... is read as
C:Usersyou... and Gradle quietly falls back to the debug key.

Do not distribute this file: a debug-signed app can never be updated.
"@
            }
        }
        else {
            Write-Host 'warning: ' -ForegroundColor Yellow -NoNewline
            Write-Host 'apksigner not found, signature unverified.'
            Write-Host '         It lives in the Android SDK under build-tools\. Set'
            Write-Host "         ANDROID_HOME, or run: apksigner verify --print-certs $out"
        }
    }
    finally {
        Pop-Location
    }
}

Write-Note 'done'
Write-Host ''
Get-ChildItem (Join-Path $dist '*.apk') | Format-Table Name, @{Name = 'Size'; Expression = { '{0:N1} MB' -f ($_.Length / 1MB) } }, LastWriteTime
Write-Host 'Hand out the files above. Each is arm64-only, which covers essentially'
Write-Host 'every phone from the last several years.'
