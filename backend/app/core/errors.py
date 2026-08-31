"""One error shape for the whole API, and documentation derived from it.

Two things a client needs from a failure: a stable identifier it can branch on,
and a sentence it may show a person. It gets both, everywhere, under ``detail``:

    {"detail": {"code": "PROPOSAL_EXPIRED", "message": "..."}}

The code is the contract; the message is not. A client that matches on message
text breaks the day someone improves the wording or translates it, so the message
is deliberately left out of every test that checks behaviour.

The documented responses are built from the same tables the routes translate
with, rather than typed out beside them. A hand-maintained ``responses=`` is
correct on the day it is written and wrong on the day someone adds an error --
and an OpenAPI document that is confidently wrong is worse than one that is
silent, because a client trusts it.
"""

from typing import Any, Protocol

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


class ErrorEnvelope(BaseModel):
    """The body of every failure this API produces."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(
        description="Stable identifier for the failure. Branch on this, never on the message."
    )
    message: str = Field(description="Safe sentence, suitable for display to a person.")


class ErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    detail: ErrorEnvelope


class CodedError(Protocol):
    """Errors that already carry their own identifier and safe wording."""

    code: str
    safe_message: str


def coded(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def responses_for(
    table: tuple[tuple[type[Exception], int], ...],
    *extra: tuple[int, str],
) -> dict[int | str, dict[str, Any]]:
    """Turn a translation table into the OpenAPI ``responses`` it justifies.

    Several errors share a status, so the description lists the codes that can
    arrive under it -- which is what a client actually needs in order to write the
    branch. ``extra`` carries statuses no table produces, such as the identity
    failures every authenticated route inherits from its dependency.
    """

    codes: dict[int, list[str]] = {}
    for error_type, status_code in table:
        code = getattr(error_type, "code", None)
        if code:
            codes.setdefault(status_code, []).append(code)
    for status_code, code in extra:
        codes.setdefault(status_code, []).append(code)
    return {
        status_code: {
            "model": ErrorResponse,
            "description": ", ".join(sorted(set(names))),
        }
        for status_code, names in sorted(codes.items())
    }


# Every route that derives an identity inherits these three from the dependency,
# so they are declared once instead of being forgotten on one route in five.
IDENTITY_RESPONSES: tuple[tuple[int, str], ...] = (
    (401, "IDENTITY_REQUIRED"),
    (500, "IDENTITY_MODE_UNSUPPORTED"),
    (503, "SESSION_STORE_UNAVAILABLE"),
)


__all__ = [
    "IDENTITY_RESPONSES",
    "CodedError",
    "ErrorEnvelope",
    "ErrorResponse",
    "coded",
    "responses_for",
]
