import hashlib
from typing import Annotated

from fastapi import Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

# The only identity mode this release implements. Kept here rather than inferred
# from the settings type, because the enforcement has to sit on the request path:
# a deployment that adds a mode to the configuration must not thereby acquire a
# request path that keeps trusting headers.
SUPPORTED_AUTH_MODE = "dev_headers"


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
    request: Request,
    tenant_id: Annotated[str, Header(alias="X-Tenant-ID")] = "development-tenant",
    user_id: Annotated[str, Header(alias="X-User-ID")] = "development-user",
) -> SecurityContext:
    """Derive the identity from headers, and only while that is the declared mode.

    These headers are unverified: whoever calls chooses the tenant. The settings
    already refuse ``production`` while the mode is ``dev_headers``, but that check
    lives far from the risk -- adding a second mode to the configuration would make
    production constructible while every route still trusted the headers, and the
    audit trail would then record a tenant the caller picked. That is worse than an
    absent trail, because the values look plausible.

    So the request path checks the mode itself. A mode this function does not
    implement fails the request rather than falling back to the headers.
    """

    # TODO(IAM): Replace this development-only dependency with verified OIDC and
    # delegated source identities. Never trust these headers behind a public proxy.
    container = getattr(request.app.state, "container", None)
    auth_mode = getattr(getattr(container, "settings", None), "auth_mode", None)
    if auth_mode != SUPPORTED_AUTH_MODE:
        raise HTTPException(
            # The deployment asked for an identity mode this build cannot derive.
            # Nothing the caller can change, and answering from headers anyway
            # would silently grant the tenant they asked for.
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "IDENTITY_MODE_UNSUPPORTED",
                "message": "The configured identity mode is not implemented",
            },
        )
    return SecurityContext(tenant_id=tenant_id, user_id=user_id)
