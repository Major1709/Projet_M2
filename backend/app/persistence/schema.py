from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)

metadata = MetaData(
    naming_convention={
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "pk": "pk_%(table_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
    }
)

conversations = Table(
    "conversations",
    metadata,
    Column("tenant_id", String(255), primary_key=True),
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("owner_user_id", String(255), nullable=False),
    Column("title", String(300), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "id",
        "owner_user_id",
        name="uq_conversations_tenant_id_id_owner_user_id",
    ),
)

action_proposals = Table(
    "action_proposals",
    metadata,
    Column("tenant_id", String(255), primary_key=True),
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("conversation_id", Uuid(as_uuid=True), nullable=False),
    Column("proposed_by_user_id", String(255), nullable=False),
    Column("source_system", String(50), nullable=False),
    Column("tool_name", String(200), nullable=False),
    Column("action_class", String(20), nullable=False),
    Column("target", JSON, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("explanation", Text, nullable=True),
    Column("diff_json", Text, nullable=True),
    Column("correlation_id", String(200), nullable=False),
    Column("execution_context_hash", String(64), nullable=False),
    Column("state", String(50), nullable=False),
    Column("version", Integer, nullable=False),
    Column("decision_token_hash", String(64), nullable=True),
    Column("supersedes_id", Uuid(as_uuid=True), nullable=True),
    Column("approved_by_user_id", String(255), nullable=True),
    Column("decision_reason", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("version >= 1", name="version_positive"),
    ForeignKeyConstraint(
        ["tenant_id", "conversation_id", "proposed_by_user_id"],
        [
            "conversations.tenant_id",
            "conversations.id",
            "conversations.owner_user_id",
        ],
        name="fk_action_proposals_tenant_conversation_owner",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "supersedes_id"],
        ["action_proposals.tenant_id", "action_proposals.id"],
        name="fk_action_proposals_tenant_supersedes",
    ),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("tenant_id", String(255), primary_key=True),
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("event_type", String(100), nullable=False),
    Column("actor_user_id", String(255), nullable=False),
    Column("correlation_id", String(200), nullable=False),
    Column("action_proposal_id", Uuid(as_uuid=True), nullable=True),
    Column("details", JSON, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "action_proposal_id"],
        ["action_proposals.tenant_id", "action_proposals.id"],
        name="fk_audit_events_tenant_action_proposal",
    ),
)
