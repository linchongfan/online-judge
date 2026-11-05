"""Create an administrator without exposing a public privilege-escalation route."""

import argparse
import getpass
import os

from sqlalchemy import select

from app.core.security import USERNAME_PATTERN, hash_password
from app.db import SessionLocal
from app.models import User, UserRole


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("email")
    args = parser.parse_args()
    if not USERNAME_PATTERN.fullmatch(args.username):
        raise SystemExit("Username must contain 3-32 letters, digits or underscores")
    password = os.environ.get("ADMIN_INITIAL_PASSWORD") or getpass.getpass("Admin password (letters+digits, min 8): ")
    if len(password) < 8 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise SystemExit("Password does not meet the policy")
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.username == args.username)) is not None:
            raise SystemExit("Username already exists")
        user = User(
            username=args.username,
            nickname="管理员",
            email=args.email.lower(),
            password_hash=hash_password(password),
            role=UserRole.ADMIN,
        )
        db.add(user)
        db.commit()
        print(f"Administrator {args.username} created")
    finally:
        db.close()


if __name__ == "__main__":
    main()
