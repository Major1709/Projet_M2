class SessionError(Exception):
    """Base class for identity failures the request path must answer."""

    code = "SESSION_ERROR"


class SessionUnavailable(SessionError):
    """The store could not be consulted, so no identity can be asserted."""

    code = "SESSION_STORE_UNAVAILABLE"
