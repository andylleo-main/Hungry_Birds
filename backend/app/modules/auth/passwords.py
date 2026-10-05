"""Password hashing, for the admin sign-in, riders and stall owners.

Uses scrypt from the standard library rather than bcrypt or argon2, which
would each add a dependency for exactly one password. scrypt is a proper
password KDF - deliberately slow and memory-hard, so guessing is expensive -
and it has been in hashlib since 3.6.

The *admin* hash is stored in an environment variable rather than the database,
which keeps that one credential out of the migration chain and puts it where the
JWT secret already lives instead of in a row a database backup carries around.
Riders and merchants cannot work that way - there are many of them and they
change their own - so each has its own table.
"""

import base64
import hashlib
import secrets

import anyio

# OWASP's floor for scrypt. n is the work factor; raising it makes both
# verification and guessing proportionally slower.
_N = 2 ** 15
_R = 8
_P = 1
_KEY_LEN = 32
_PREFIX = "scrypt"

# scrypt needs roughly 128 * n * r bytes, which at these parameters is about
# 33MB - just over OpenSSL's 32MB default, which otherwise refuses with
# "memory limit exceeded". Stated explicitly so the cost is visible rather
# than being discovered as a runtime error.
_MAX_MEM = 96 * 1024 * 1024


def hash_password(password: str) -> str:
    """Returns a self-describing hash: the parameters travel with it, so the
    cost can be raised later without stranding existing hashes."""
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_LEN, maxmem=_MAX_MEM
    )
    return "$".join(
        [
            _PREFIX,
            str(_N),
            str(_R),
            str(_P),
            base64.b64encode(salt).decode(),
            base64.b64encode(key).decode(),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check against a stored hash. False for anything
    malformed, so a corrupted or half-pasted value fails closed rather than
    raising into a 500."""
    try:
        prefix, n, r, p, salt_b64, key_b64 = encoded.split("$")
        if prefix != _PREFIX:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(key_b64)
        candidate = hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=_MAX_MEM,
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return secrets.compare_digest(candidate, expected)


def waste_time_like_a_verification() -> None:
    """Burn the same work as a real check, for a login attempt on an address
    that has no password set.

    Without it, a wrong address returns noticeably faster than a wrong
    password, and that difference tells an attacker which addresses are worth
    attacking.
    """
    hashlib.scrypt(
        b"timing", salt=b"timing-salt-1234", n=_N, r=_R, p=_P, dklen=_KEY_LEN, maxmem=_MAX_MEM
    )


async def hash_password_async(password: str) -> str:
    """scrypt, off the event loop.

    hash_password is ~33MB and tens of milliseconds of CPU by design. The admin
    signs in rarely enough for that to be invisible, but riders sign in every
    shift and stall owners every morning, and they mistype often, so on a single
    container doing this inline would stall every other request in flight.
    anyio's worker thread is what FastAPI already uses for sync endpoints.
    """
    return await anyio.to_thread.run_sync(hash_password, password)


async def verify_password_async(password: str, encoded: str) -> bool:
    return await anyio.to_thread.run_sync(verify_password, password, encoded)


async def waste_time_like_a_verification_async() -> None:
    """The timing decoy, off the event loop for the same reason as above."""
    await anyio.to_thread.run_sync(waste_time_like_a_verification)
