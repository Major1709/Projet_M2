from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


router = APIRouter(tags=["health"])


def _readiness(request: Request) -> HealthResponse:
    if not request.app.state.container.readiness_probe():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is not ready",
        )
    return HealthResponse()


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    return _readiness(request)


@router.get("/health/live", response_model=HealthResponse)
def liveness() -> HealthResponse:
    return HealthResponse()


@router.get("/health/ready", response_model=HealthResponse)
def readiness(request: Request) -> HealthResponse:
    return _readiness(request)
