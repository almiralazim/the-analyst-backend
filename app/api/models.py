"""Models endpoint: returns available LLM providers for frontend dropdown."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.llm.model_registry import ModelRegistry
from app.models.user import User
from app.rate_limit import limiter
from app.config import settings
from app.services.auth import get_current_user

router = APIRouter(prefix="/models", tags=["models"])


class ModelOption(BaseModel):
    """Single option for the frontend model selection dropdown."""

    value: str
    label: str
    provider: str | None = None
    description: str
    tier: str | None = None


class ModelsResponseData(BaseModel):
    """Response payload for GET /api/v1/models."""

    options: list[ModelOption]
    default: str = "auto"
    warning: str | None = None


@router.get(
    "",
    summary="List available LLM models",
    response_description="Dropdown-ready list of available models and providers",
)
@limiter.limit(settings.rate_limit_default)
async def list_models(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
):
    """Return available LLM providers and models for the model selection UI.

    Only includes providers whose API keys are configured. The response is
    structured for direct use in a frontend dropdown component.

    **Authentication:** Required — Bearer token in `Authorization` header.
    """
    registry = ModelRegistry()
    available = registry.get_available_providers()

    options: list[ModelOption] = [
        ModelOption(
            value="auto",
            label="Auto (Recommended)",
            provider=None,
            description="Automatically selects the best model for each agent based on task complexity",
            tier=None,
        )
    ]

    for provider in available:
        default_model = next(
            (m for m in provider.models if m.is_default), None
        )
        if default_model:
            options.append(ModelOption(
                value=provider.name,
                label=f"{provider.label} - {default_model.label}",
                provider=provider.name,
                description=default_model.description,
                tier=default_model.tier,
            ))

        for model in provider.models:
            if not model.is_default:
                options.append(ModelOption(
                    value=model.id,
                    label=f"{provider.label} - {model.label}",
                    provider=provider.name,
                    description=model.description,
                    tier=model.tier,
                ))

    warning = None
    if not available:
        warning = (
            "No LLM providers are configured. "
            "Set at least one API key to enable model selection."
        )

    return {"data": ModelsResponseData(
        options=options,
        default="auto",
        warning=warning,
    )}
