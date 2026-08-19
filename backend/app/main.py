from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.api import router as agent_router
from app.approvals.api import router as approvals_router
from app.auth.api import router as auth_router
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
    if resolved_settings.frontend_origins:
        # Installed only when a front end has been named, and shaped by the identity
        # mode rather than fixed.
        #
        # Session mode carries the identity in a cookie, so the browser must be
        # allowed to attach it -- a cross-origin front end otherwise sends nothing
        # and every call answers 401, which reads as a broken sign-in rather than a
        # missing header. That permission is only safe because the origin list is
        # explicit: the specification forbids pairing credentials with a wildcard,
        # and this build never has one to offer.
        #
        # Header mode carries the identity in two headers instead, so no cookie
        # needs attaching, and allowing them anyway would widen what a browser sends
        # for no gain.
        session_mode = resolved_settings.auth_mode == "session"
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.frontend_origins),
            allow_credentials=session_mode,
            allow_methods=["GET", "POST"],
            allow_headers=(
                ["Content-Type"]
                if session_mode
                else ["Content-Type", "X-Tenant-ID", "X-User-ID"]
            ),
        )
    app.include_router(health_router)
    app.include_router(conversations_router)
    app.include_router(approvals_router)
    app.include_router(mcp_router)
    app.include_router(agent_router)
    app.include_router(auth_router)
    return app


app = create_app()
