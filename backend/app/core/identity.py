import hashlib
from typing import Annotated

from fastapi import Header
from pydantic import BaseModel, ConfigDict, Field


class SecurityContext(BaseModel):
    """Server-derived identity context; it must never be supplied by the LLM."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)


def security_context_fingerprint(context: SecurityContext) -> str:
    """Bind a proposal to the server-derived identity without exposing credentials."""

    value = f"{context.tenant_id}\x1f{context.user_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def get_development_security_context(
    tenant_id: Annotated[str, Header(alias="X-Tenant-ID")] = "development-tenant",
    user_id: Annotated[str, Header(alias="X-User-ID")] = "development-user",
) -> SecurityContext:
    # TODO(IAM): Replace this development-only dependency with verified OIDC and
    # delegated source identities. Never trust these headers behind a public proxy.
    return SecurityContext(tenant_id=tenant_id, user_id=user_id)
