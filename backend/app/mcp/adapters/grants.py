import hmac
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import anyio

from app.core.identity import SecurityContext
from app.mcp.domain import MCPProvider
from app.mcp.errors import MCPGrantUnavailable

MAX_BEARER_TOKEN_BYTES = 16 * 1024


@dataclass(frozen=True)
class BearerGrant:
    """Ephemeral adapter-only grant material. Its representation never contains the token."""

    provider: MCPProvider
    tenant_id: str
    user_id: str
    access_token: str = field(repr=False)


class DelegatedGrantBroker(Protocol):
    async def acquire(
        self,
        *,
        provider: MCPProvider,
        context: SecurityContext,
    ) -> BearerGrant: ...


@dataclass(frozen=True)
class DevelopmentGrantBinding:
    provider: MCPProvider
    tenant_id: str
    user_id: str
    token_file: Path


class UnavailableGrantBroker:
    async def acquire(
        self,
        *,
        provider: MCPProvider,
        context: SecurityContext,
    ) -> BearerGrant:
        del provider, context
        raise MCPGrantUnavailable()


class DevelopmentFileGrantBroker:
    """Development-only broker that rereads a mounted secret for each connection."""

    def __init__(
        self,
        *,
        environment: str,
        bindings: tuple[DevelopmentGrantBinding, ...],
    ) -> None:
        if environment not in {"development", "test"}:
            raise ValueError("Development file grants are forbidden in this environment")
        indexed: dict[MCPProvider, DevelopmentGrantBinding] = {}
        for binding in bindings:
            if binding.provider in indexed:
                raise ValueError("Only one development grant binding is allowed per provider")
            indexed[binding.provider] = binding
        self._bindings = indexed

    async def acquire(
        self,
        *,
        provider: MCPProvider,
        context: SecurityContext,
    ) -> BearerGrant:
        binding = self._bindings.get(provider)
        if binding is None:
            raise MCPGrantUnavailable()
        if not hmac.compare_digest(binding.tenant_id, context.tenant_id) or not hmac.compare_digest(
            binding.user_id, context.user_id
        ):
            raise MCPGrantUnavailable()

        try:
            raw = await anyio.to_thread.run_sync(binding.token_file.read_bytes)
        except OSError as error:
            raise MCPGrantUnavailable() from error
        token_bytes = raw.rstrip(b"\r\n")
        if (
            len(token_bytes) < 16
            or len(token_bytes) > MAX_BEARER_TOKEN_BYTES
            or any(byte < 0x21 or byte > 0x7E for byte in token_bytes)
        ):
            raise MCPGrantUnavailable()
        try:
            token = token_bytes.decode("ascii")
        except UnicodeDecodeError as error:  # pragma: no cover - guarded by byte range
            raise MCPGrantUnavailable() from error
        return BearerGrant(
            provider=provider,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            access_token=token,
        )
