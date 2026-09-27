"""Guards on deployment configuration that code review alone would miss."""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

START_COMMAND_FILES = [
    REPO / "railway.json",
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


def test_healthcheck_targets_the_readiness_probe():
    """/health/ready checks Postgres and Redis; /health only proves the process
    is up, so a deploy that cannot reach its databases would still go live."""
    config = json.loads((REPO / "railway.json").read_text())
    assert config["deploy"]["healthcheckPath"] == "/health/ready"


def test_migrations_run_before_a_release_takes_traffic():
    config = json.loads((REPO / "railway.json").read_text())
    assert "alembic upgrade head" in config["deploy"]["preDeployCommand"]


def test_the_example_env_does_not_ship_a_usable_secret():
    example = (REPO / "backend" / ".env.example").read_text()
    for line in example.splitlines():
        if line.startswith("JWT_SECRET="):
            value = line.split("=", 1)[1]
            assert "change-me" in value, "the example must not look like a real secret"
        # Credentials must never be committed, even as examples.
        if line.startswith(("RESEND_API_KEY=", "CLOUDINARY_API_SECRET=")):
            assert line.split("=", 1)[1].strip() == ""
