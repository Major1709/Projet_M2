from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.api import router as agent_router
from app.approvals.api import router as approvals_router
from app.bootstrap import ApplicationContainer, build_container
from app.conversations.api import router as conversations_router
from app.core.config import Settings, get_settings
from app.health.api import router as health_router
from app.mcp.api import router as mcp_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        engine = app.state.container.engine
        if engine is not None:
            engine.dispose()


def create_app(
    settings: Settings | None = None,
    container: ApplicationContainer | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_container = container or build_container(resolved_settings)

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.container = resolved_container
    app.include_router(health_router)
    app.include_router(conversations_router)
    app.include_router(approvals_router)
    app.include_router(mcp_router)
    app.include_router(agent_router)
    return app


app = create_app()
