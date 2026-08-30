from app.approvals.errors import InvalidTransition
from app.mcp.domain import SourceSystem


class NoMutationToolsPin:
    """Denies every mutation tool, because no mutation registry exists yet.

    Control 3 of the integration report -- a default-deny registry with closed schemas
    -- is satisfied for reads only. Until it covers mutations there is no authenticated
    schema to pin a proposal to, and inventing one would let a proposal claim a shape
    nobody published. Refusing here keeps the approval path buildable and testable
    without opening a write surface: the day mutation contracts land, this adapter is
    replaced by one that reads them, and nothing above it changes.
    """

    def schema_sha256(self, *, source_system: SourceSystem, tool_name: str) -> str:
        raise InvalidTransition(
            f"No mutation contract is registered for {source_system}.{tool_name}"
        )
