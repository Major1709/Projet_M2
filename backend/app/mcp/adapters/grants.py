import asyncio
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import anyio
import httpx2

from app.core.identity import SecurityContext
from app.mcp.domain import MCPBindingKind, MCPProvider
from app.mcp.errors import MCPGrantUnavailable

MAX_BEARER_TOKEN_BYTES = 16 * 1024
MAX_CREDENTIALS_BYTES = 64 * 1024
# Renew slightly early. The remaining lifetime is measured here but spent on the
# far side of a connection, so a token that is merely "not expired yet" can still
# lapse mid-call; this margin makes that race disappear.
REFRESH_SKEW_SECONDS = 120.0
REFRESH_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class BearerGrant:
    """Ephemeral adapter-only grant material. Its representation never contains the token."""

    provider: MCPProvider
    binding: MCPBindingKind
    tenant_id: str
    user_id: str
    access_token: str = field(repr=False)


class DelegatedGrantBroker(Protocol):
    async def acquire(
        self,
        *,
        provider: MCPProvider,
        binding: MCPBindingKind,
        context: SecurityContext,
    ) -> BearerGrant: ...


@dataclass(frozen=True)
class DevelopmentGrantBinding:
    """One development grant: either a static token, or a credentials document.

    A static ``token_file`` holds a bearer token and nothing else, so it dies with
    that token and has to be replaced by hand. A ``credentials_file`` also holds the
    refresh token, which lets the broker trade an expired grant for a fresh one
    without a human -- the difference between re-authorising every working day and
    authorising once.
    """

    provider: MCPProvider
    binding: MCPBindingKind
    tenant_id: str
    user_id: str
    token_file: Path | None = None
    credentials_file: Path | None = None
    token_endpoint: str | None = None

    def __post_init__(self) -> None:
        if (self.token_file is None) == (self.credentials_file is None):
            raise ValueError("A grant binding needs exactly one of token_file or credentials_file")
        if self.credentials_file is None:
            return
        if self.token_endpoint is None:
            raise ValueError("A credentials binding requires its token endpoint")
        if urlsplit(self.token_endpoint).scheme != "https":
            raise ValueError("A token endpoint must be https")


class UnavailableGrantBroker:
    async def acquire(
        self,
        *,
        provider: MCPProvider,
        binding: MCPBindingKind,
        context: SecurityContext,
    ) -> BearerGrant:
        del provider, binding, context
        raise MCPGrantUnavailable()


def _validated_token(raw: str) -> str:
    """Reject anything that is not a plausible bearer token, without echoing it."""

    token = raw.strip()
    encoded = token.encode("utf-8", errors="replace")
    if (
        len(encoded) < 16
        or len(encoded) > MAX_BEARER_TOKEN_BYTES
        or any(byte < 0x21 or byte > 0x7E for byte in encoded)
    ):
        raise MCPGrantUnavailable()
    return token


class RenewableCredentialsFile:
    """A delegated OAuth document on disk that renews itself before it expires.

    The refresh token is long-lived and the access token is not, so holding both
    turns an interactive authorisation into a one-off. Renewal rewrites the file:
    Atlassian rotates the refresh token on every exchange, and dropping the new one
    would strand the deployment back on manual re-authorisation.
    """

    def __init__(self, *, path: Path, token_endpoint: str) -> None:
        self._path = path
        self._token_endpoint = token_endpoint
        # asyncio, not anyio: this is constructed during synchronous bootstrap, and
        # asyncio locks are the ones guaranteed to bind lazily to the running loop.
        # Serialising renewals matters because the refresh token rotates -- two
        # concurrent exchanges would race, and the loser's token is already revoked.
        self._lock = asyncio.Lock()

    async def access_token(self) -> str:
        async with self._lock:
            document = await anyio.to_thread.run_sync(self._read)
            expires_at = document.get("expires_at")
            if (
                isinstance(expires_at, int | float)
                and time.time() < expires_at - REFRESH_SKEW_SECONDS
            ):
                return _validated_token(str(document.get("access_token", "")))
            renewed = await self._renew(document)
            await anyio.to_thread.run_sync(self._write, renewed)
            return _validated_token(str(renewed.get("access_token", "")))

    def _read(self) -> dict[str, Any]:
        try:
            raw = self._path.read_bytes()
        except OSError as error:
            raise MCPGrantUnavailable() from error
        if len(raw) > MAX_CREDENTIALS_BYTES:
            raise MCPGrantUnavailable()
        try:
            document = json.loads(raw)
        except ValueError as error:
            raise MCPGrantUnavailable() from error
        if not isinstance(document, dict):
            raise MCPGrantUnavailable()
        return document

    def _write(self, document: dict[str, Any]) -> None:
        # Same directory, then replace: a crash mid-write must not leave a truncated
        # document behind, because that would cost the refresh token permanently.
        temporary = self._path.with_name(f"{self._path.name}.partial")
        try:
            handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(document, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise MCPGrantUnavailable() from error

    async def _renew(self, document: dict[str, Any]) -> dict[str, Any]:
        refresh_token = document.get("refresh_token")
        client_id = document.get("client_id")
        if not isinstance(refresh_token, str) or not isinstance(client_id, str):
            raise MCPGrantUnavailable()
        form = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
        # Public clients authenticate with the client_id alone; Figma advertises only
        # client_secret_* and rejects that. The secret is sent in the form rather than
        # in Basic auth because both providers accept the former, and one code path
        # that works everywhere beats two that differ per provider.
        client_secret = document.get("client_secret")
        if isinstance(client_secret, str) and client_secret:
            form["client_secret"] = client_secret
        try:
            async with httpx2.AsyncClient(
                timeout=REFRESH_TIMEOUT_SECONDS,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.post(
                    self._token_endpoint,
                    data=form,
                    headers={"Accept": "application/json"},
                )
        except httpx2.HTTPError as error:
            raise MCPGrantUnavailable() from error
        if response.status_code != 200:
            # The body carries the provider's error code and sometimes the grant
            # itself, so it is deliberately not attached to the raised error.
            raise MCPGrantUnavailable()
        try:
            payload = response.json()
        except ValueError as error:
            raise MCPGrantUnavailable() from error
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise MCPGrantUnavailable()

        renewed = dict(document)
        renewed["access_token"] = payload["access_token"]
        if isinstance(payload.get("refresh_token"), str):
            renewed["refresh_token"] = payload["refresh_token"]
        expires_in = payload.get("expires_in")
        # An absent lifetime is treated as already expired rather than assumed: the
        # next read then renews again, which is wasteful but never serves a dead token.
        renewed["expires_at"] = (
            time.time() + float(expires_in) if isinstance(expires_in, int | float) else 0.0
        )
        return renewed


class DevelopmentFileGrantBroker:
    """Development-only broker that rereads its mounted grant for each connection."""

    def __init__(
        self,
        *,
        environment: str,
        bindings: tuple[DevelopmentGrantBinding, ...],
    ) -> None:
        if environment not in {"development", "test"}:
            raise ValueError("Development file grants are forbidden in this environment")
        # Keyed by (provider, binding): a delegated Atlassian token covers exactly
        # one site, so Jira and Confluence need their own grant as soon as they are
        # hosted on different sites. Every combination is registered explicitly at
        # startup rather than resolved by fallback here, so no read can silently
        # borrow another binding's token.
        indexed: dict[tuple[MCPProvider, MCPBindingKind], DevelopmentGrantBinding] = {}
        for entry in bindings:
            key = (entry.provider, entry.binding)
            if key in indexed:
                raise ValueError("Only one development grant binding is allowed per binding kind")
            indexed[key] = entry
        self._bindings = indexed
        # One renewer per file, not per binding: two bindings may be served by the
        # same document, and they must then share the lock that serialises rotation.
        self._credentials: dict[Path, RenewableCredentialsFile] = {}
        for entry in indexed.values():
            if entry.credentials_file is None or entry.token_endpoint is None:
                continue
            self._credentials.setdefault(
                entry.credentials_file,
                RenewableCredentialsFile(
                    path=entry.credentials_file,
                    token_endpoint=entry.token_endpoint,
                ),
            )

    async def acquire(
        self,
        *,
        provider: MCPProvider,
        binding: MCPBindingKind,
        context: SecurityContext,
    ) -> BearerGrant:
        entry = self._bindings.get((provider, binding))
        if entry is None:
            raise MCPGrantUnavailable()
        if not hmac.compare_digest(entry.tenant_id, context.tenant_id) or not hmac.compare_digest(
            entry.user_id, context.user_id
        ):
            raise MCPGrantUnavailable()

        if entry.credentials_file is not None:
            token = await self._credentials[entry.credentials_file].access_token()
        else:
            token = await self._static_token(entry)
        return BearerGrant(
            provider=provider,
            binding=binding,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            access_token=token,
        )

    @staticmethod
    async def _static_token(entry: DevelopmentGrantBinding) -> str:
        assert entry.token_file is not None
        try:
            raw = await anyio.to_thread.run_sync(entry.token_file.read_bytes)
        except OSError as error:
            raise MCPGrantUnavailable() from error
        try:
            decoded = raw.rstrip(b"\r\n").decode("ascii")
        except UnicodeDecodeError as error:
            raise MCPGrantUnavailable() from error
        return _validated_token(decoded)
