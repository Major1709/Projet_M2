from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@router.get("/health/live", response_model=HealthResponse)
def liveness() -> HealthResponse:
    return HealthResponse()


@router.get("/health/ready", response_model=HealthResponse)
def readiness() -> HealthResponse:
    # The MVP only uses in-process adapters. Add dependency checks when
    # PostgreSQL, Redis and remote MCP servers become required for readiness.
    return HealthResponse()
