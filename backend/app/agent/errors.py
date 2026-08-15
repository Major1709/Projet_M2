class LLMError(Exception):
    """Expected fail-closed error whose message is safe for an API response.

    Mirrors the MCP taxonomy deliberately: the orchestration layer sits between two
    outbound dependencies, and one shape of error for both keeps the API translation
    honest. A provider that answers correctly and a network that is broken must not
    collapse into the same code -- that conflation was corrected twice on the MCP
    transports and is avoided here from the start.
    """

    code = "LLM_CALL_FAILED"
    safe_message = "The language model call could not be completed"

    def __init__(self) -> None:
        super().__init__(self.safe_message)


class LLMCredentialUnavailable(LLMError):
    code = "LLM_CREDENTIAL_UNAVAILABLE"
    safe_message = "No usable language model credential is available"


class LLMDNSRejected(LLMError):
    code = "LLM_DNS_REJECTED"
    safe_message = "The language model endpoint address is not approved"


class LLMTransportFailure(LLMError):
    code = "LLM_TRANSPORT_FAILURE"
    safe_message = "The language model provider is unavailable"


class LLMRateLimited(LLMError):
    code = "LLM_RATE_LIMITED"
    safe_message = "The language model provider is rate limiting this credential"


class LLMRequestTooLarge(LLMError):
    """The request's own token budget exceeds what the credential may spend.

    Distinct from ``LLMRateLimited`` because the remedy differs: waiting does not
    help, the request has to get smaller. Groq answers 413 for this even though it
    labels the cause a rate limit, and collapsing the two would tell the caller to
    back off when it should be trimming its prompt or its completion ceiling.
    """

    code = "LLM_REQUEST_TOO_LARGE"
    safe_message = "The request exceeds the token budget allowed for this credential"


class LLMCallTimeout(LLMError):
    code = "LLM_CALL_TIMEOUT"
    safe_message = "The language model did not respond within the allowed time"


class LLMProviderRefused(LLMError):
    code = "LLM_PROVIDER_REFUSED"
    safe_message = "The language model provider refused the request"


class LLMInvalidResponse(LLMError):
    code = "LLM_INVALID_RESPONSE"
    safe_message = "The language model returned an invalid response"


class LLMResponseTooLarge(LLMError):
    code = "LLM_RESPONSE_TOO_LARGE"
    safe_message = "The language model response exceeds the allowed size"
