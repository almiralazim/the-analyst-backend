"""Seed script: create an initial admin user from environment variables.

Usage:
    python -m app.seed

Reads ADMIN_EMAIL and ADMIN_PASSWORD from environment (or .env file).
Skips creation if the user already exists. Safe to run multiple times.
"""

from __future__ import annotations

import asyncio
import os
import sys

from app.config import settings


async def seed_admin() -> None:
    """Create the admin user if it doesn't already exist."""
    email = os.environ.get("ADMIN_EMAIL", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "").strip()
    display_name = os.environ.get("ADMIN_DISPLAY_NAME", "Admin").strip()

    if not email or not password:
        print(
            "ERROR: ADMIN_EMAIL and ADMIN_PASSWORD environment variables are required.\n"
            "Set them in your .env file or pass them directly."
        )
        sys.exit(1)

    if len(password) < 8:
        print("ERROR: ADMIN_PASSWORD must be at least 8 characters.")
        sys.exit(1)

    from sqlalchemy import select

    from app.database import async_session_factory, engine
    from app.database import Base
    from app.models.user import User
    from app.services.auth import hash_password

    # Ensure tables exist (in case migrations haven't run yet)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.email == email))
        existing = result.scalar_one_or_none()

        if existing:
            print(f"User '{email}' already exists (id: {existing.id}). Skipping.")
            return

        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
            role="admin",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        print("Admin user created successfully:")
        print(f"  Email: {email}")
        print(f"  Display Name: {display_name}")
        print(f"  ID: {user.id}")
        print("\nYou can now login at POST /api/v1/auth/login")


def main() -> None:
    asyncio.run(seed_admin())


if __name__ == "__main__":
    main()
