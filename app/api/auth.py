"""Authentication endpoints: register, login, refresh, me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.rate_limit import limiter
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenRefreshResponse,
    UserResponse,
)
from app.schemas.common import ApiResponse
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=ApiResponse[AuthResponse],
    response_model_exclude_none=True,
    status_code=201,
    summary="Register a new user account",
    response_description="User created successfully with access and refresh tokens",
    responses={
        409: {"description": "Email already registered", "content": {"application/json": {"example": {"error": {"code": "CONFLICT", "message": "Email already registered"}}}}},
        422: {"description": "Validation error (invalid email format, password too short)", "content": {"application/json": {"example": {"detail": [{"loc": ["body", "email"], "msg": "value is not a valid email address", "type": "value_error.email"}]}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Create a new user account and return authentication tokens.

    **Authentication:** None required (public endpoint)

    **Request Body:**
    - `email` (string, required): Valid email address. Must be unique across all accounts.
    - `password` (string, required): Minimum 8 characters, maximum 128 characters.
    - `display_name` (string, optional): User's display name, max 100 characters.

    **Response (201):**
    ```json
    {
      "data": {
        "user": {"id": "uuid", "email": "user@example.com", "display_name": "...", "role": "user", "preferences": {}, "created_at": "..."},
        "access_token": "eyJhbGciOiJIUzI1NiIs...",
        "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
        "token_type": "bearer",
        "expires_in": 3600
      }
    }
    ```

    **Errors:**
    - `409 Conflict`: Email already registered — user must login or use a different email.
    - `422 Unprocessable Entity`: Invalid input (bad email format, password shorter than 8 chars).

    **Frontend Integration:**
    - Store `access_token` in memory (not localStorage for security).
    - Store `refresh_token` in an HttpOnly cookie or secure storage.
    - Use `access_token` in `Authorization: Bearer <token>` header for all subsequent requests.
    - Token expires in `expires_in` seconds; refresh before expiry using `/auth/refresh`.
    - After registration, the user is automatically logged in — no separate login call needed.
    """
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CONFLICT", "message": "Email already registered"},
        )

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    db.add(user)
    await db.flush()

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    return ApiResponse(data=AuthResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    ))


@router.post(
    "/login",
    response_model=ApiResponse[AuthResponse],
    response_model_exclude_none=True,
    summary="Authenticate with email and password",
    response_description="Authentication successful with access and refresh tokens",
    responses={
        401: {"description": "Invalid email or password", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Invalid email or password"}}}}},
        422: {"description": "Validation error (missing fields)", "content": {"application/json": {"example": {"detail": [{"loc": ["body", "email"], "msg": "field required", "type": "value_error.missing"}]}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate a user and return access + refresh tokens.

    **Authentication:** None required (public endpoint)

    **Request Body:**
    - `email` (string, required): The user's registered email address.
    - `password` (string, required): The user's password.

    **Response (200):**
    ```json
    {
      "data": {
        "access_token": "eyJhbGciOiJIUzI1NiIs...",
        "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
        "token_type": "bearer",
        "expires_in": 3600
      }
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Invalid email or password. The error message is intentionally
      generic to prevent email enumeration attacks.
    - `422 Unprocessable Entity`: Missing required fields.

    **Frontend Integration:**
    - On success, store tokens the same way as after registration.
    - On 401, show a generic "Invalid credentials" message — do not distinguish between
      wrong email vs. wrong password for security reasons.
    - Implement rate-limit-aware retry: if you receive 429, wait for `Retry-After` header value.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid email or password"},
        )

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    return ApiResponse(data=AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_expire_minutes * 60,
    ))


@router.post(
    "/refresh",
    response_model=ApiResponse[TokenRefreshResponse],
    response_model_exclude_none=True,
    summary="Refresh an expired access token",
    response_description="New access token issued successfully",
    responses={
        401: {"description": "Invalid or expired refresh token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Invalid refresh token"}}}}},
        422: {"description": "Validation error (missing refresh_token)", "content": {"application/json": {"example": {"detail": [{"loc": ["body", "refresh_token"], "msg": "field required", "type": "value_error.missing"}]}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def refresh(request: Request, body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token for a new access token.

    **Authentication:** None required (uses refresh_token in body)

    **Request Body:**
    - `refresh_token` (string, required): A valid, non-expired refresh token
      obtained from `/auth/register` or `/auth/login`.

    **Response (200):**
    ```json
    {
      "data": {
        "access_token": "eyJhbGciOiJIUzI1NiIs...",
        "expires_in": 3600
      }
    }
    ```

    **Errors:**
    - `401 Unauthorized`: The refresh token is invalid, expired, or has the wrong type.

    **Frontend Integration:**
    - Call this endpoint before the access token expires (check `expires_in` from login).
    - Implement a token refresh interceptor in your HTTP client:
      1. If a request returns 401, attempt a token refresh.
      2. If refresh succeeds, retry the original request with the new access token.
      3. If refresh fails (401), redirect to login.
    - Refresh tokens expire after 7 days. After that, the user must re-authenticate.
    """
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "Invalid refresh token"},
        )

    import uuid
    user_id = uuid.UUID(payload["sub"])
    access_token = create_access_token(user_id)

    return ApiResponse(data=TokenRefreshResponse(
        access_token=access_token,
        expires_in=settings.access_token_expire_minutes * 60,
    ))


@router.get(
    "/me",
    response_model=ApiResponse[UserResponse],
    response_model_exclude_none=True,
    summary="Get current user profile",
    response_description="Current user profile information",
    responses={
        401: {"description": "Missing or invalid access token", "content": {"application/json": {"example": {"error": {"code": "UNAUTHORIZED", "message": "Could not validate credentials"}}}}},
    },
)
@limiter.limit(settings.rate_limit_default)
async def me(request: Request, user: User = Depends(get_current_user)):
    """Return the authenticated user's profile information.

    **Authentication:** Required — Bearer token in `Authorization` header.

    **Response (200):**
    ```json
    {
      "data": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "email": "user@example.com",
        "display_name": "Jane Doe",
        "role": "user",
        "preferences": {},
        "created_at": "2025-01-15T10:30:00Z"
      }
    }
    ```

    **Errors:**
    - `401 Unauthorized`: Access token is missing, malformed, or expired.

    **Frontend Integration:**
    - Call this on app initialization to verify the stored token is still valid.
    - Use the response to populate user profile UI and determine role-based access.
    - If this returns 401, trigger the token refresh flow or redirect to login.
    """
    return ApiResponse(data=UserResponse.model_validate(user))
