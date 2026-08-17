class MCPReadError(Exception):
    """Expected fail-closed error whose message is safe for an API response."""

    code = "MCP_READ_FAILED"
    safe_message = "The MCP read could not be completed"

    def __init__(self) -> None:
        super().__init__(self.safe_message)


class MCPProviderDisabled(MCPReadError):
    code = "MCP_PROVIDER_DISABLED"
    safe_message = "The requested MCP provider is disabled"


class MCPToolDenied(MCPReadError):
    code = "MCP_TOOL_DENIED"
    safe_message = "The requested MCP tool is not approved for read access"


class MCPInputRejected(MCPReadError):
    code = "MCP_INPUT_REJECTED"
    safe_message = "The MCP tool arguments are invalid"


class MCPBindingUnavailable(MCPReadError):
    code = "MCP_BINDING_UNAVAILABLE"
    safe_message = "The requested MCP source binding is unavailable"


class MCPGrantUnavailable(MCPReadError):
    code = "MCP_GRANT_UNAVAILABLE"
    safe_message = "No matching delegated MCP grant is available"


class MCPAuditUnavailable(MCPReadError):
    code = "MCP_AUDIT_UNAVAILABLE"
    safe_message = "The MCP read audit trail is unavailable"


class MCPDNSRejected(MCPReadError):
    code = "MCP_DNS_REJECTED"
    safe_message = "The MCP endpoint address is not approved"


class MCPProtocolRejected(MCPReadError):
    code = "MCP_PROTOCOL_REJECTED"
    safe_message = "The MCP server protocol version is not approved"


class MCPSchemaRejected(MCPReadError):
    code = "MCP_SCHEMA_REJECTED"
    safe_message = "The MCP tool schema is not approved"


class MCPTransportFailure(MCPReadError):
    code = "MCP_TRANSPORT_FAILURE"
    safe_message = "The MCP provider is unavailable"


class MCPRateLimited(MCPReadError):
    code = "MCP_RATE_LIMITED"
    safe_message = "The MCP provider is rate limiting this credential"


class MCPCallTimeout(MCPReadError):
    code = "MCP_CALL_TIMEOUT"
    safe_message = "The MCP provider did not respond within the allowed time"


class MCPRemoteToolFailure(MCPReadError):
    code = "MCP_REMOTE_TOOL_FAILURE"
    safe_message = "The MCP provider refused the read"


class MCPInvalidResponse(MCPReadError):
    code = "MCP_INVALID_RESPONSE"
    safe_message = "The MCP provider returned an invalid response"


class MCPResponseTooLarge(MCPReadError):
    code = "MCP_RESPONSE_TOO_LARGE"
    safe_message = "The MCP provider response exceeds the allowed size"
