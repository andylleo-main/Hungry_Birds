"""The push chain across the backend and the two Android apps.

A notification needs four separate files to agree, in two languages and a repo
the backend test suite does not otherwise look at. Nothing checks that agreement
at build time, and every way of breaking it fails the same silent way: the
notification is accepted by Firebase, delivered to the phone, and then dropped or
shown on a low-importance channel that makes no sound. The app looks fine. A
stall misses a lunch rush, or a rider never learns they were given a delivery,
and there is nothing on any screen to say why.

So it is asserted here, where pytest already runs, rather than left to whoever
next edits one of the four.

This cannot test that a notification actually arrives - that needs a device, a
Play Services connection and a real Firebase project. What it can do is make sure
the strings line up, which is the part that has gone wrong.
"""

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# app directory, the channel the backend sends it, and the applicationId the
# Gradle plugin matches google-services.json on.
APPS = [
    ("merchant_app", "orders", "food.hungrybirds.merchant"),
    ("rider_app", "deliveries", "food.hungrybirds.rider"),
]
IDS = [app for app, _, _ in APPS]


def android(app: str, *parts: str) -> Path:
    return REPO / "apps" / app / "android" / Path(*parts)


def main_activity(app: str) -> Path:
    found = list((REPO / "apps" / app / "android").rglob("MainActivity.kt"))
    assert len(found) == 1, f"{app}: expected one MainActivity.kt, found {found}"
    return found[0]


def test_the_backend_sends_exactly_the_two_channels_the_apps_create():
    """Neither app would hear a third one.

    A channel is created in MainActivity.onCreate and nowhere else, so a new
    channel_id added to the service without a matching app change is a
    notification that arrives on a channel the phone has never been told about.
    """
    service = (REPO / "backend" / "app" / "modules" / "notifications" / "service.py").read_text()
    sent = set(re.findall(r'channel_id="([a-z_]+)"', service))
    assert sent == {"orders", "deliveries"}, (
        f"the backend sends {sorted(sent)}; the apps create ['deliveries', 'orders']"
    )


@pytest.mark.parametrize(("app", "channel", "_app_id"), APPS, ids=IDS)
def test_the_manifest_names_the_channel_the_backend_sends(app, channel, _app_id):
    """Android, not our code, draws the notification when the app is closed.

    It reads the default channel from this meta-data. A name that does not match
    what the backend puts in the message leaves Android with no channel to use.
    """
    manifest = android(app, "app", "src", "main", "AndroidManifest.xml").read_text()
    match = re.search(
        r'android:name="com\.google\.firebase\.messaging\.default_notification_channel_id"\s+'
        r'android:value="([^"]+)"',
        manifest,
    )
    assert match, f"{app}: no default notification channel declared in the manifest"
    assert match.group(1) == channel


@pytest.mark.parametrize(("app", "channel", "_app_id"), APPS, ids=IDS)
def test_the_app_actually_creates_that_channel(app, channel, _app_id):
    """Naming a channel does not create it.

    This is the specific trap: the manifest entry and the backend can agree
    perfectly and the phone still falls back to a low-importance default,
    because nothing ever called createNotificationChannel. The result is a
    notification that arrives silently, which is the same as not arriving.
    """
    source = main_activity(app).read_text()
    created = re.search(r"NotificationChannel\(\s*\"([a-z_]+)\"", source)
    assert created, f"{app}: MainActivity never calls createNotificationChannel"
    assert created.group(1) == channel, (
        f"{app}: MainActivity creates {created.group(1)!r}, the backend sends {channel!r}"
    )
    assert "createNotificationChannel" in source, (
        f"{app}: a NotificationChannel is built but never registered"
    )
    assert "IMPORTANCE_HIGH" in source, (
        f"{app}: the channel is not high importance, so it will not make a sound "
        "or show a heads-up banner - which is the entire point of it"
    )


@pytest.mark.parametrize(("app", "_channel", "_app_id"), APPS, ids=IDS)
def test_notifications_are_permitted_at_all(app, _channel, _app_id):
    """Android 13+ drops notifications without this, and drops them silently."""
    manifest = android(app, "app", "src", "main", "AndroidManifest.xml").read_text()
    assert "android.permission.POST_NOTIFICATIONS" in manifest


@pytest.mark.parametrize(("app", "_channel", "_app_id"), APPS, ids=IDS)
def test_the_release_build_can_reach_the_network(app, _channel, _app_id):
    """Flutter's template declares INTERNET only for debug and profile.

    A release APK built without it installs, runs, and fails every request
    instantly - which reads on screen as "can't reach the server, check your
    connection" on a phone with full signal. That is exactly what the merchant
    app's first signed APK did.
    """
    manifest = android(app, "app", "src", "main", "AndroidManifest.xml").read_text()
    assert "android.permission.INTERNET" in manifest


@pytest.mark.parametrize(("app", "_channel", "app_id"), APPS, ids=IDS)
def test_google_services_json_has_a_client_for_this_app(app, _channel, app_id):
    """The Gradle plugin matches on applicationId and fails the build without one.

    It is also what firebase_core reads at startup, so a mismatch is the
    difference between a phone that can receive a token and one that cannot.
    """
    config = json.loads(android(app, "app", "google-services.json").read_text())
    packages = {
        client["client_info"]["android_client_info"]["package_name"]
        for client in config["client"]
    }
    assert app_id in packages, f"{app}: no google-services.json client for {app_id}"


@pytest.mark.parametrize(("app", "_channel", "app_id"), APPS, ids=IDS)
def test_the_application_id_matches_the_namespace_and_has_not_drifted(app, _channel, app_id):
    """Android identifies an installed app by its applicationId.

    Changing it is not free: existing installs cannot take an update and have to
    be uninstalled first. It has already moved twice (see the comment in
    build.gradle.kts), so it is pinned rather than left to a reviewer to notice.
    """
    gradle = android(app, "app", "build.gradle.kts").read_text()
    assert f'applicationId = "{app_id}"' in gradle
    assert f'namespace = "{app_id}"' in gradle
    package = main_activity(app).read_text().splitlines()[0]
    assert package == f"package {app_id}"


def test_the_two_apps_do_not_share_an_application_id():
    """They install side by side on a stall owner's phone, and often do."""
    ids = {app_id for _, _, app_id in APPS}
    assert len(ids) == len(APPS)


@pytest.mark.parametrize(("app", "_channel", "_app_id"), APPS, ids=IDS)
def test_the_apps_still_point_at_the_live_api_by_default(app, _channel, _app_id):
    """A compile-time constant, so a forgotten --dart-define is not a build that
    fails - it is a build that installs, runs and silently reaches nothing.

    Defaulting to the production host means the worst a forgotten flag can do is
    point at the right server. scripts/build_apks.sh requires the flag anyway.
    """
    config = (REPO / "apps" / app / "lib" / "app_config.dart").read_text()
    assert "defaultValue: 'https://www.hungrybirds.food/api'" in config, (
        f"{app}: the default API base URL is not the live deployment"
    )
