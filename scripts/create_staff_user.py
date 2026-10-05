"""Create a staff account for the admin console (support agents and reviewers).

Usage: python scripts/create_staff_user.py <username> [--display-name "Priya S"]
       python scripts/create_staff_user.py <username> --reset-password

The password is prompted for (not echoed), or read from STAFF_PASSWORD for automated setups.
Customers never need an account.
"""
import argparse
import getpass
import os
import sys

import _bootstrap  # noqa: F401

from app.database import create_all, init_engine, session_scope
from app.services.auth import create_user, set_password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("username")
    parser.add_argument("--display-name", help="Name customers see on agent replies (default: the username)")
    parser.add_argument("--reset-password", action="store_true", help="Set a new password for an existing account")
    args = parser.parse_args()
    password = os.environ.get("STAFF_PASSWORD") or getpass.getpass("Password (at least 10 characters): ")
    if not os.environ.get("STAFF_PASSWORD") and getpass.getpass("Repeat password: ") != password:
        print("Passwords do not match.", file=sys.stderr)
        return 1
    init_engine()
    create_all()
    try:
        with session_scope() as db:
            if args.reset_password:
                set_password(db, args.username, password)
            else:
                create_user(db, args.username, password, args.display_name or args.username)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{'Updated the password for' if args.reset_password else 'Created'} staff account {args.username!r}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
