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


@router.post("/register", response_model=ApiResponse[AuthResponse], status_code=201)
@limiter.limit(settings.rate_limit_default)
async def register(request: Request, body: RegisterRequest, db: AsyncSession = Depends(get_db)):
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


@router.post("/login", response_model=ApiResponse[AuthResponse])
@limiter.limit(settings.rate_limit_default)
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)):
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


@router.post("/refresh", response_model=ApiResponse[TokenRefreshResponse])
@limiter.limit(settings.rate_limit_default)
async def refresh(request: Request, body: RefreshRequest, db: AsyncSession = Depends(get_db)):
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


@router.get("/me", response_model=ApiResponse[UserResponse])
@limiter.limit(settings.rate_limit_default)
async def me(request: Request, user: User = Depends(get_current_user)):
    return ApiResponse(data=UserResponse.model_validate(user))
