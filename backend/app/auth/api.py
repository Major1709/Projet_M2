from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.auth.errors import SignInDisabled, SignInError
from app.auth.workflow import AtlassianSignIn
from app.sessions.domain import SESSION_COOKIE_NAME, session_token_hash

router = APIRouter(prefix="/api/auth/atlassian", tags=["auth"])


def get_sign_in(request: Request) -> AtlassianSignIn:
    sign_in = getattr(request.app.state.container, "sign_in", None)
    if sign_in is None:
        # The deployment has not registered an OAuth app. Exposing a route that can
        # only fail would look like an outage rather than a configuration choice.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": SignInDisabled.code, "message": SignInDisabled.safe_message},
        )
    return sign_in


def _cookie_is_secure(request: Request) -> bool:
    """Secure everywhere except plain-HTTP localhost, where it would never be sent.

    Deriving this from the request rather than hardcoding it keeps the development
    loop usable without ever weakening a deployed one: anything that is not local
    plain HTTP gets the flag.
    """

    return not (request.url.scheme == "http" and request.url.hostname in {"localhost", "127.0.0.1"})


@router.get("/start")
def start_sign_in(request: Request) -> RedirectResponse:
    sign_in = get_sign_in(request)
    # 307 rather than 302: the method must be preserved, and a GET that silently
    # becomes something else is a class of bug nobody enjoys finding here.
    return RedirectResponse(sign_in.begin(), status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/callback")
async def complete_sign_in(
    request: Request,
    code: Annotated[str, Query(min_length=1, max_length=2_000)],
    state: Annotated[str, Query(min_length=1, max_length=200)],
) -> RedirectResponse:
    sign_in = get_sign_in(request)
    try:
        token = await sign_in.complete(code=code, state=state)
    except SignInError as error:
        # The provider's own words never reach here: they can echo the code or
        # describe the failure for an operator.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": error.code, "message": error.safe_message},
        ) from error

    settings = request.app.state.container.settings
    response = RedirectResponse(
        settings.atlassian_oauth_post_login_path,
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        # httponly: script cannot read it, so an injected script cannot exfiltrate
        # the session. samesite=lax: not sent on cross-site POSTs, which is the
        # cheap half of CSRF defence. path=/: the whole API is behind it.
        httponly=True,
        secure=_cookie_is_secure(request),
        samesite="lax",
        path="/",
        max_age=int(settings.session_lifetime_hours * 3_600),
    )
    return response


@router.post("/signout", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(
    request: Request,
    response: Response,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> None:
    """Revoke server-side, then clear the cookie.

    Both, and in that order. Clearing only the cookie would leave a live session
    behind for anyone who already copied the token -- precisely the case signing out
    is meant to answer. Revoking without clearing would leave the browser presenting
    a dead token and reading 401 on every call.
    """

    store = getattr(request.app.state.container, "sessions", None)
    if session_token and store is not None:
        store.revoke(session_token_hash(session_token))
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
