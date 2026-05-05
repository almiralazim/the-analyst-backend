"""Integration tests for the authentication flow.

Covers register, login, token refresh, and the /auth/me protected endpoint.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_register_new_user(client: AsyncClient):
    """Registering a new user returns 201 with user data and tokens."""
    email = f"newuser-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "SecurePass123!",
            "display_name": "New User",
        },
    )

    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["user"]["email"] == email
    assert body["user"]["display_name"] == "New User"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


async def test_register_duplicate_email(client: AsyncClient):
    """Registering with an already-used email returns 409."""
    email = f"dup-{uuid.uuid4().hex[:8]}@example.com"
    payload = {"email": email, "password": "SecurePass123!"}

    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


async def test_login_correct_credentials(client: AsyncClient):
    """Logging in with valid credentials returns 200 with tokens."""
    email = f"login-{uuid.uuid4().hex[:8]}@example.com"
    password = "SecurePass123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] > 0


async def test_login_wrong_password(client: AsyncClient):
    """Logging in with the wrong password returns 401."""
    email = f"wrongpw-{uuid.uuid4().hex[:8]}@example.com"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "SecurePass123!"},
    )

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPassword!"},
    )

    assert resp.status_code == 401


async def test_login_nonexistent_email(client: AsyncClient):
    """Logging in with an email that was never registered returns 401."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "nobody@example.com",
            "password": "DoesNotMatter1!",
        },
    )

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------


async def test_refresh_token(authenticated_user: dict, client: AsyncClient):
    """Refreshing with a valid refresh token returns 200 and a new access token."""
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": authenticated_user["refresh_token"]},
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["access_token"]
    assert body["expires_in"] > 0


async def test_refresh_with_invalid_token(client: AsyncClient):
    """Refreshing with a garbage token returns 401."""
    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "not-a-real-token"},
    )

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Protected endpoint: /auth/me
# ---------------------------------------------------------------------------


async def test_me_with_valid_token(
    authenticated_user: dict,
    client: AsyncClient,
):
    """Accessing /auth/me with a valid token returns the user profile."""
    resp = await client.get(
        "/api/v1/auth/me",
        headers=authenticated_user["headers"],
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["email"] == authenticated_user["email"]
    assert body["id"] == authenticated_user["user_id"]


async def test_me_without_token(client: AsyncClient):
    """Accessing /auth/me without a token returns 401 or 403."""
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code in (401, 403)
