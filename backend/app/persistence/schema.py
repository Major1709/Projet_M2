from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
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

from app.semantics.domain import EMBEDDING_DIMENSIONS

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

conversation_messages = Table(
    "conversation_messages",
    metadata,
    Column("tenant_id", String(255), primary_key=True),
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("conversation_id", Uuid(as_uuid=True), nullable=False),
    Column("author_user_id", String(255), nullable=False),
    # Explicit rank within the thread. Ordering on the timestamp alone is not
    # reliable: both turns of one exchange are written inside a single clock
    # tick on some platforms, and the tie then falls to a random identifier --
    # a conversation that displays backwards now and then, irreproducibly.
    Column("sequence", Integer, nullable=False),
    Column("role", String(20), nullable=False),
    Column("content", Text, nullable=False),
    Column("correlation_id", String(200), nullable=False),
    Column("status", String(20), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("sequence >= 0", name="sequence_not_negative"),
    CheckConstraint("role in ('user', 'assistant')", name="role_known"),
    CheckConstraint("status in ('complete', 'error')", name="status_known"),
    UniqueConstraint(
        "tenant_id",
        "conversation_id",
        "sequence",
        name="uq_conversation_messages_tenant_id_conversation_id_sequence",
    ),
    # Same composite reference as the proposals: pointing at the owner column too
    # makes "only the owner writes into this conversation" a database invariant
    # rather than a check some future caller can forget.
    ForeignKeyConstraint(
        ["tenant_id", "conversation_id", "author_user_id"],
        [
            "conversations.tenant_id",
            "conversations.id",
            "conversations.owner_user_id",
        ],
        name="fk_conversation_messages_tenant_conversation_owner",
    ),
)

message_sources = Table(
    "message_sources",
    metadata,
    Column("tenant_id", String(255), primary_key=True),
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("message_id", Uuid(as_uuid=True), nullable=False),
    # The order the reads were first consulted in. Stored rather than recomputed:
    # a citation list whose order changes between two readings of the same answer
    # would look like the answer changed.
    Column("position", Integer, nullable=False),
    Column("source_system", String(50), nullable=False),
    Column("tool_name", String(200), nullable=False),
    # Null for a read that enumerates rather than designates -- a project list, a
    # search. There is no column for a confidence score or an inferred flag, and
    # that is deliberate: the backend derives citations from the provenance of
    # performed reads, so it has nothing to put in them, and a column invites a
    # value.
    Column("resource_reference", String(2_000), nullable=True),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("truncated", Boolean, nullable=False),
    CheckConstraint("position >= 0", name="position_not_negative"),
    UniqueConstraint(
        "tenant_id",
        "message_id",
        "position",
        name="uq_message_sources_tenant_id_message_id_position",
    ),
    ForeignKeyConstraint(
        ["tenant_id", "message_id"],
        ["conversation_messages.tenant_id", "conversation_messages.id"],
        name="fk_message_sources_tenant_message",
    ),
)

sessions = Table(
    "sessions",
    metadata,
    # No tenant_id in the primary key, unlike every other table here: a session is
    # what *establishes* the tenant, so it cannot be scoped by one. It is addressed
    # by the hash of a 256-bit token instead, which is unguessable on its own.
    Column("id", Uuid(as_uuid=True), primary_key=True),
    # The token itself is never stored. A leaked dump must not yield live sessions.
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("tenant_id", String(200), nullable=False),
    Column("user_id", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
)


document_embeddings = Table(
    "document_embeddings",
    metadata,
    Column("tenant_id", String(200), primary_key=True),
    Column("id", Uuid(as_uuid=True), nullable=False, unique=True),
    Column("source_system", String(50), primary_key=True),
    # The provider's own identifier -- a Jira key, a Confluence page id. Part of
    # the primary key so re-indexing a document updates it rather than adding a
    # second vector for the same thing, which would let one ticket outvote the
    # rest of the corpus simply by having been indexed twice.
    Column("external_id", String(200), primary_key=True),
    Column("title", String(1000), nullable=False),
    Column("resource_reference", String(1000)),
    # Which model produced this vector. Vectors from two models share a dimension
    # count and nothing else, so comparing across them yields confident nonsense.
    # Recorded rather than assumed, a model change becomes detectable.
    Column("model_name", String(200), nullable=False),
    Column("content_digest", String(64), nullable=False),
    Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
    Column("indexed_at", DateTime(timezone=True), nullable=False),
)
