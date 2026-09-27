"""Generate the ADMIN_PASSWORD_HASH value for an admin password.

Usage (from backend/, venv active):

    PYTHONPATH=. python scripts/set_admin_password.py

It prompts without echoing, confirms, and prints the hash to paste into
Railway. The password itself is never stored, printed, or sent anywhere - only
the hash, which cannot be turned back into the password.

Setting the variable enables POST /api/auth/admin/login. Leaving it unset
means that endpoint does not exist at all.
"""

import getpass
import sys

from app.modules.auth.passwords import hash_password

MIN_LENGTH = 12


def main() -> None:
    password = getpass.getpass("Admin password: ")
    if len(password) < MIN_LENGTH:
        # This one password opens the whole admin panel and is guessable in a
        # way a one-time code is not, so the floor is higher than usual.
        print(f"Too short - use at least {MIN_LENGTH} characters.", file=sys.stderr)
        sys.exit(1)
    if password != getpass.getpass("Confirm: "):
        print("They don't match.", file=sys.stderr)
        sys.exit(1)

    print()
    print("Set this on Railway as ADMIN_PASSWORD_HASH:")
    print()
    print(f"  {hash_password(password)}")
    print()
    print("The password itself is not stored anywhere. Keep it in your password")
    print("manager - there is no way to recover it from the hash above.")


if __name__ == "__main__":
    main()
