import hashlib
from typing import Annotated

from fastapi import Cookie, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.sessions.domain import SESSION_COOKIE_NAME, session_token_hash
from app.sessions.errors import SessionError

# The modes this build can actually derive an identity for. Enforcement sits on the
# request path rather than being inferred from the settings type: a deployment that
# adds a mode to the configuration must not thereby acquire a request path that
# keeps trusting whatever it was already trusting.
DEV_HEADERS_MODE = "dev_headers"
SESSION_MODE = "session"
SUPPORTED_AUTH_MODES = frozenset({DEV_HEADERS_MODE, SESSION_MODE})


class SecurityContext(BaseModel):
    """Server-derived identity context; it must never be supplied by the LLM."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)


def security_context_fingerprint(context: SecurityContext) -> str:
    """Bind a proposal to the server-derived identity without exposing credentials."""

    value = f"{context.tenant_id}\x1f{context.user_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _unsupported_mode() -> HTTPException:
    # The deployment asked for an identity mode this build cannot derive. Nothing the
    # caller can change, and answering from the headers anyway would silently grant
    # the tenant they asked for.
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "IDENTITY_MODE_UNSUPPORTED",
            "message": "The configured identity mode is not implemented",
        },
    )


def _no_identity() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "IDENTITY_REQUIRED",
            "message": "No active session",
        },
    )


def _from_session(request: Request, token: str | None) -> SecurityContext:
    """Derive the identity from a server-held session, or refuse.

    The identity headers are deliberately not consulted here, not even as a
    fallback: the whole point of this mode is that the caller stops choosing their
    own tenant, and a fallback would hand it straight back.
    """

    if not token:
        raise _no_identity()
    store = getattr(request.app.state.container, "sessions", None)
    if store is None:
        raise _unsupported_mode()
    try:
        session = store.get_by_token_hash(session_token_hash(token))
    except SessionError as error:
        # Fail closed. An unreachable store means no identity can be asserted, and
        # asserting one anyway is exactly the failure this mode exists to prevent.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": error.code,
                "message": "Sessions cannot be verified right now",
            },
        ) from error
    if session is None or not session.is_active():
        # Expired reads the same as absent on purpose: telling a caller that their
        # session existed but lapsed says something about a token they may not own.
        raise _no_identity()
    return SecurityContext(tenant_id=session.tenant_id, user_id=session.user_id)


def get_security_context(
    request: Request,
    tenant_id: Annotated[str, Header(alias="X-Tenant-ID")] = "development-tenant",
    user_id: Annotated[str, Header(alias="X-User-ID")] = "development-user",
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> SecurityContext:
    """Derive the caller's identity according to the declared mode, or refuse.

    ``dev_headers`` trusts two unverified headers: whoever calls picks the tenant.
    The settings refuse ``production`` in that mode, but that check lives far from
    the risk -- adding a second mode to the configuration would make production
    constructible while every route still trusted the headers, and the audit trail
    would then record a tenant the caller chose. That is worse than an absent trail,
    because the values look plausible. So the request path decides for itself, and a
    mode it does not implement fails the request rather than falling back.
    """

    container = getattr(request.app.state, "container", None)
    mode = getattr(getattr(container, "settings", None), "auth_mode", None)
    if mode == SESSION_MODE:
        return _from_session(request, session_token)
    if mode == DEV_HEADERS_MODE:
        # TODO(IAM): retire this mode once the sign-in flow exists. Never trust these
        # headers behind a public proxy.
        return SecurityContext(tenant_id=tenant_id, user_id=user_id)
    raise _unsupported_mode()
