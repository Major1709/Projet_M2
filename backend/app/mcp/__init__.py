"""Public interface of the MCP integration module."""

from app.mcp.domain import (
    MCPExecutionResult,
    MCPToolCall,
    PermissionCheck,
    PermissionDecision,
    SourceSystem,
    ToolActionClass,
)
from app.mcp.ports import MCPToolGateway, SourcePermissionVerifier

__all__ = [
    "MCPExecutionResult",
    "MCPToolCall",
    "MCPToolGateway",
    "PermissionCheck",
    "PermissionDecision",
    "SourcePermissionVerifier",
    "SourceSystem",
    "ToolActionClass",
]
