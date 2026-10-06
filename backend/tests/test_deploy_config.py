"""Guards on deployment configuration that code review alone would miss."""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# railway.json used to be here. Railway deprecated Config as Code and stopped
# reading it, so it was deleted; see the deployment section of README.md.
START_COMMAND_FILES = [
    REPO / "backend" / "Dockerfile",
    REPO / "backend" / "Procfile",
]


@pytest.mark.parametrize("path", START_COMMAND_FILES, ids=lambda p: p.name)
def test_uvicorn_is_started_without_proxy_header_handling(path):
    """Every start command must pass --no-proxy-headers.

    Uvicorn's default rewrites request.client from the leftmost X-Forwarded-For
    entry, which is the one a caller can forge. The rate limiter reads that
    header itself, from the right, counting only hops it is told to trust - and
    that is defeated outright if uvicorn has already substituted a forged value
    underneath it. Dropping this flag silently makes every per-IP limit in
    app/core/limits.py bypassable, with nothing failing to show it, which is
    why it is asserted here rather than left to a comment.
    """
    text = path.read_text()
    assert "uvicorn" in text, f"{path.name} no longer starts uvicorn; update this test"
    for line in text.splitlines():
        if "uvicorn app.main:app" in line and "--reload" not in line:
            assert "--no-proxy-headers" in line, f"{path.name}: {line.strip()}"


def test_the_required_service_settings_are_still_written_down():
    """The deploy settings live on the Railway service now, not in this repo.

    They used to be asserted directly against railway.json. Railway deprecated
    Config as Code and silently ignored that file, which is how a deployment came
    up with a migration step it was never running and a database with no tables.
    Deleting the file removed the lie; it also removed the only thing a test could
    check, because nothing in a repository can reach a service's settings.

    So this guards the replacement: the README is now the sole record of what has
    to be set by hand, and losing it would mean the next person rebuilding this
    service has nothing to go on. Each string below is a setting whose absence
    breaks the deploy in a way that does not announce itself - no tables, a
    healthcheck that passes while the database is unreachable, or an API that
    serves while the web app 404s.
    """
    readme = (REPO / "README.md").read_text()
    for required in (
        "alembic upgrade head",
        "/health/ready",
        "backend/Dockerfile",
    ):
        assert required in readme, (
            f"README.md no longer documents {required!r}. It is the only place "
            "this is recorded - the Railway service cannot be configured from "
            "this repository."
        )


def test_the_example_env_does_not_ship_a_usable_secret():
    example = (REPO / "backend" / ".env.example").read_text()
    for line in example.splitlines():
        if line.startswith("JWT_SECRET="):
            value = line.split("=", 1)[1]
            assert "change-me" in value, "the example must not look like a real secret"
        # Credentials must never be committed, even as examples.
        if line.startswith(("RESEND_API_KEY=", "CLOUDINARY_API_SECRET=")):
            assert line.split("=", 1)[1].strip() == ""


def test_an_emptied_boolean_flag_does_not_stop_the_app_booting():
    """Clearing a variable in a dashboard means emptying it, not deleting it.

    pydantic rejects "" for a bool, so the obvious way to switch one of these off
    used to crash the service on its next deploy - with an error naming a
    demo-data flag rather than anything to do with the deploy that failed. Both
    The flag this was written for was SEED_DEMO_DATA, which is gone; the
    behaviour it taught is not, and the next bool added will be copied from this
    one.
    """
    from app.core.config import Settings

    base = {"database_url": "postgresql+asyncpg://x/y", "secret_key": "k" * 32}
    assert Settings(**base, otp_debug_echo="").otp_debug_echo is False

    # Real values still parse the way they always did.
    assert Settings(**base, otp_debug_echo="1").otp_debug_echo is True


def test_a_short_jwt_secret_refuses_to_start():
    """HS256 with a key shorter than its hash is weaker than the hash, and nothing
    looks wrong at runtime - tokens sign, verify and work. PyJWT only warns, and a
    warning in a log nobody reads is not a control, so this fails at boot."""
    import pytest
    from pydantic import ValidationError

    from app.core.config import Settings

    base = {"database_url": "postgresql+asyncpg://x/y"}
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(**base, jwt_secret="too-short")

    # Exactly at the boundary is fine; one byte under is not.
    assert Settings(**base, jwt_secret="k" * 32).jwt_secret == "k" * 32
    with pytest.raises(ValidationError):
        Settings(**base, jwt_secret="k" * 31)
