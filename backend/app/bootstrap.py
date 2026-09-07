from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Engine

from app.agent.adapters.gemini import GeminiLLMProvider
from app.agent.adapters.groq import GroqLLMProvider
from app.agent.audit import AuditedLLMProvider
from app.agent.domain import LLMProvider
from app.agent.mutation_workflow import ApprovedMutationRunner
from app.agent.read_workflow import AgentReadWorkflow
from app.approvals.adapters.memory import InMemoryApprovalUnitOfWork
from app.approvals.adapters.postgres import PostgresApprovalUnitOfWorkFactory
from app.approvals.adapters.tool_pin import NoMutationToolsPin, RegistryMutationToolPin
from app.approvals.workflow import ApprovalWorkflow
from app.audit.adapters.postgres import PostgresAppendOnlyAuditWriter
from app.audit.ports import AuditSink
from app.auth.adapters.memory import (
    InMemoryDelegatedGrantSink,
    InMemoryPendingAuthorizationStore,
)
from app.auth.adapters.postgres import PostgresDelegatedGrantStore
from app.auth.client import AtlassianOAuthClient
from app.auth.crypto import GrantCipher, load_key
from app.auth.ports import DelegatedGrantSink
from app.auth.workflow import AtlassianSignIn
from app.conversations.adapters.memory import (
    InMemoryConversationMessageRepository,
    InMemoryConversationRepository,
)
from app.conversations.adapters.postgres import (
    PostgresConversationMessageRepository,
    PostgresConversationRepository,
)
from app.conversations.workflow import ConversationWorkflow
from app.core.config import Settings
from app.core.database import (
    create_database_engine,
    create_session_factory,
    database_is_ready,
)
from app.mcp.adapters.figma_rest import FigmaRESTTransport
from app.mcp.adapters.grants import (
    DevelopmentFileGrantBroker,
    DevelopmentGrantBinding,
    UnavailableGrantBroker,
)
from app.mcp.adapters.idempotency import PostgresMutationIdempotencyStore
from app.mcp.adapters.mutation_gateway import MCPMutationGateway
from app.mcp.adapters.permission import SourceReadPermissionVerifier
from app.mcp.adapters.remote import SDKRemoteMCPTransport
from app.mcp.adapters.routing import ProviderRoutedTransport
from app.mcp.domain import MCPBindingKind, MCPProvider, MCPReadSourceSystem
from app.mcp.read_workflow import MCPReadWorkflow
from app.mcp.registry import (
    ATLASSIAN_TOKEN_ENDPOINT,
    FIGMA_TOKEN_ENDPOINT,
    MCPToolRegistry,
)
from app.semantics.adapters.local_model import LocalEmbeddingProvider
from app.semantics.adapters.memory import InMemoryEmbeddingStore
from app.semantics.adapters.postgres import PostgresEmbeddingStore
from app.semantics.ports import EmbeddingStore
from app.semantics.workflow import SemanticIndex
from app.sessions.adapters.memory import InMemorySessionStore
from app.sessions.adapters.postgres import PostgresSessionStore
from app.sessions.ports import SessionStore


@dataclass(frozen=True)
class ApplicationContainer:
    """Application services and owned infrastructure resources."""

    approvals: ApprovalWorkflow
    audit: AuditSink | None
    conversations: ConversationWorkflow
    mcp_reads: MCPReadWorkflow
    readiness_probe: Callable[[], bool]
    # Consulted on every request in session mode, and never in dev_headers mode.
    sessions: SessionStore
    settings: Settings
    # Absent when no language model provider is configured. The MCP reads stay
    # available in that case: the assistant is the optional layer, not the
    # connectors underneath it.
    agent: AgentReadWorkflow | None = None
    # Absent unless the deployment registered an Atlassian OAuth app. The sign-in
    # route then refuses rather than existing and always failing.
    sign_in: AtlassianSignIn | None = None
    # Absent unless the deployment enabled embeddings. The reindex route then
    # refuses rather than existing and always failing.
    semantic_index: SemanticIndex | None = None
    engine: Engine | None = None
    # Absent tant que les ecritures ne sont pas activees, et c'est le comportement
    # voulu : une route de mutation qui existe et refuse toujours apprend a un
    # attaquant que la surface est la. Absente, elle n'apprend rien.
    mutations: ApprovedMutationRunner | None = None


def build_container(settings: Settings) -> ApplicationContainer:
    if settings.repository_backend == "memory":
        conversation_repository = InMemoryConversationRepository()
        message_repository = InMemoryConversationMessageRepository()
        session_store: SessionStore = InMemorySessionStore()
        approval_uow_factory = InMemoryApprovalUnitOfWork()
        mcp_reads = _build_mcp_read_workflow(settings, approval_uow_factory.audit)
        semantic_index = _build_semantic_index(settings, InMemoryEmbeddingStore())
        grants: DelegatedGrantSink = _build_grant_sink(settings, None)
        return ApplicationContainer(
            approvals=ApprovalWorkflow(
                approval_uow_factory,
                conversation_repository,
                _mutation_tool_pin(settings),
                settings.approval_ttl_seconds,
                settings.auth_mode,
            ),
            audit=approval_uow_factory.audit,
            conversations=ConversationWorkflow(conversation_repository, message_repository),
            mcp_reads=mcp_reads,
            agent=_build_agent(
                settings, approval_uow_factory.audit, mcp_reads, semantic_index
            ),
            semantic_index=semantic_index,
            readiness_probe=lambda: True,
            sessions=session_store,
            settings=settings,
            sign_in=_build_sign_in(settings, session_store, grants),
        )

    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    conversation_repository = PostgresConversationRepository(session_factory)
    message_repository = PostgresConversationMessageRepository(session_factory)
    session_store = PostgresSessionStore(session_factory)
    approval_uow_factory = PostgresApprovalUnitOfWorkFactory(session_factory)
    audit_writer = PostgresAppendOnlyAuditWriter(session_factory)
    mcp_reads = _build_mcp_read_workflow(settings, audit_writer)
    semantic_index = _build_semantic_index(settings, PostgresEmbeddingStore(session_factory))
    grants = _build_grant_sink(settings, session_factory)
    return ApplicationContainer(
        approvals=ApprovalWorkflow(
                approval_uow_factory,
                conversation_repository,
                _mutation_tool_pin(settings),
                settings.approval_ttl_seconds,
                settings.auth_mode,
            ),
        audit=audit_writer,
        conversations=ConversationWorkflow(conversation_repository, message_repository),
        mcp_reads=mcp_reads,
        agent=_build_agent(settings, audit_writer, mcp_reads, semantic_index),
        semantic_index=semantic_index,
        mutations=_build_mutations(
            settings, approval_uow_factory, mcp_reads, session_factory
        ),
        readiness_probe=lambda: database_is_ready(engine),
        sessions=session_store,
        settings=settings,
        sign_in=_build_sign_in(settings, session_store, grants),
        engine=engine,
    )


def _build_sign_in(
    settings: Settings,
    sessions: SessionStore,
    grants: DelegatedGrantSink,
) -> AtlassianSignIn | None:
    if not settings.atlassian_oauth_enabled:
        return None
    # The settings already refuse an enabled sign-in without these three, so the
    # assertions describe an invariant rather than guarding an input.
    assert settings.atlassian_oauth_client_id is not None
    assert settings.atlassian_oauth_client_secret_file is not None
    assert settings.atlassian_oauth_redirect_uri is not None
    secret = settings.atlassian_oauth_client_secret_file.read_text(encoding="utf-8").strip()
    return AtlassianSignIn(
        client=AtlassianOAuthClient(
            client_id=settings.atlassian_oauth_client_id,
            client_secret=secret,
            redirect_uri=settings.atlassian_oauth_redirect_uri,
        ),
        pending=InMemoryPendingAuthorizationStore(),
        sessions=sessions,
        grants=grants,
        client_id=settings.atlassian_oauth_client_id,
        redirect_uri=settings.atlassian_oauth_redirect_uri,
        session_lifetime=timedelta(hours=settings.session_lifetime_hours),
        expected_cloud_id=settings.atlassian_expected_cloud_id,
    )


def _build_grant_sink(settings: Settings, session_factory: object | None):
    """The durable grant store, or the memory one.

    Falls back rather than fails: a deployment without an encryption key must not
    write refresh tokens to disk in the clear, and it must not refuse to start
    either. Losing grants on restart costs a consent; storing them unsealed costs
    considerably more.
    """

    if settings.token_encryption_key_file is None or session_factory is None:
        return InMemoryDelegatedGrantSink()
    cipher = GrantCipher(load_key(settings.token_encryption_key_file.read_text()))
    return PostgresDelegatedGrantStore(session_factory, cipher)


def _build_semantic_index(settings: Settings, store: EmbeddingStore) -> SemanticIndex | None:
    """The index, or nothing at all.

    Off by default. The runtime weighs about 2,3 Go and downloads a model on
    first use, so a deployment that has not asked for retrieval must not acquire
    it by upgrading. Absent, the assistant answers exactly as it did before.
    """

    if not settings.embeddings_enabled:
        return None
    return SemanticIndex(
        provider=LocalEmbeddingProvider(settings.embedding_model),
        store=store,
    )


def _offered_systems(settings: Settings) -> frozenset[MCPReadSourceSystem]:
    """Les connecteurs qu'il est honnete de proposer au modele.

    Derive des memes drapeaux qui autorisent une lecture, et d'eux seuls : deux
    listes decrivant la meme decision divergent, et celle qui diverge ici offrirait
    un outil que l'autre refuse.

    ATLASSIAN designe les outils communs aux deux produits -- l'identite du compte et
    la liste des ressources accessibles -- et suit donc le drapeau du socle, pas celui
    d'un produit. Les rattacher a Jira les aurait fait disparaitre d'un deploiement
    Confluence seul.
    """

    actifs = {
        MCPReadSourceSystem.ATLASSIAN: settings.mcp_atlassian_enabled,
        MCPReadSourceSystem.JIRA: settings.mcp_jira_enabled,
        MCPReadSourceSystem.CONFLUENCE: settings.mcp_confluence_enabled,
        MCPReadSourceSystem.FIGMA: settings.mcp_figma_enabled,
    }
    return frozenset(systeme for systeme, actif in actifs.items() if actif)


def _mutation_tool_pin(settings: Settings):
    """L'epinglage suit la configuration, pas la disponibilite du registre.

    Un deploiement qui n'ouvre pas les ecritures refuse par le nom de son adaptateur
    plutot que par un registre qui se trouverait vide : l'intention se lit, au lieu de
    se deduire d'une collection.
    """

    if not settings.mcp_mutations_enabled:
        return NoMutationToolsPin()
    return RegistryMutationToolPin()


def _build_mutations(
    settings: Settings,
    approval_uow_factory,
    mcp_reads: MCPReadWorkflow,
    session_factory,
) -> ApprovedMutationRunner | None:
    """Le chemin d'ecriture, monte seulement quand la configuration l'autorise.

    La verification des preconditions n'est pas refaite ici : Settings les a deja
    tranchees, et deux endroits qui verifient la meme regle finissent par en verifier
    deux differentes.
    """

    if not settings.mcp_mutations_enabled:
        return None
    return ApprovedMutationRunner(
        unit_of_work=approval_uow_factory,
        gateway=MCPMutationGateway(
            settings=settings,
            transport=mcp_reads._transport,
        ),
        # Le meme workflow de lecture que celui de l'assistant : la revalidation juste
        # avant l'ecriture doit passer par les memes autorisations et laisser la meme
        # trace qu'une lecture ordinaire.
        permission_verifier=SourceReadPermissionVerifier(reads=mcp_reads),
        tool_pin=RegistryMutationToolPin(),
        idempotency=PostgresMutationIdempotencyStore(session_factory),
    )


def _build_llm_provider(settings: Settings) -> LLMProvider | None:
    """The one place a provider is chosen, so the choice is readable in one screen.

    Returning ``None`` rather than raising is the existing contract for "no model
    configured": the agent route is then simply absent, and the rest of the API --
    reads, approvals, the audit trail -- comes up as usual. Settings validation has
    already refused the ambiguous case where both providers are enabled, so the
    order of these branches carries no meaning.
    """

    if settings.llm_groq_enabled and settings.llm_groq_api_key_file is not None:
        return GroqLLMProvider(
            api_key_file=settings.llm_groq_api_key_file,
            model=settings.llm_groq_model,
            max_completion_tokens=settings.llm_groq_max_completion_tokens,
        )
    if settings.llm_gemini_enabled and settings.llm_gemini_api_key_file is not None:
        return GeminiLLMProvider(
            api_key_file=settings.llm_gemini_api_key_file,
            model=settings.llm_gemini_model,
            max_completion_tokens=settings.llm_gemini_max_completion_tokens,
        )
    return None


def _build_agent(
    settings: Settings,
    audit_sink: AuditSink,
    mcp_reads: MCPReadWorkflow,
    semantic_index: SemanticIndex | None = None,
) -> AgentReadWorkflow | None:
    provider = _build_llm_provider(settings)
    if provider is None:
        return None
    return AgentReadWorkflow(
        # The audit decorator is applied here rather than left to the caller: an
        # invocation that leaves no trace of its tenant and user must not be
        # reachable, and the only way to guarantee that is for the unwrapped
        # provider never to enter the container.
        provider=AuditedLLMProvider(
            provider=provider,
            audit_sink=audit_sink,
        ),
        reads=mcp_reads,
        # Filtre ce qui est PRESENTE, jamais ce qui est autorise : le registre reste
        # l'autorite, et un outil cache ici aurait de toute facon ete refuse par son
        # connecteur eteint.
        offered_systems=_offered_systems(settings),
        # The same sink the provider and the reads write to, so a question and
        # everything it caused share one trail.
        audit_sink=audit_sink,
        semantic_index=semantic_index,
    )


def _build_mcp_read_workflow(settings: Settings, audit_sink: AuditSink) -> MCPReadWorkflow:
    if settings.mcp_grant_backend == "development_files":
        bindings: list[DevelopmentGrantBinding] = []
        if (
            settings.mcp_atlassian_grant_tenant_id is not None
            and settings.mcp_atlassian_grant_user_id is not None
        ):
            # One entry per binding kind: a delegated token covers a single site, so
            # Jira and Confluence get their own grant when they live on separate sites
            # and fall back to the provider-wide one otherwise. The mapping is fixed
            # here at startup, so the broker never has to guess at call time.
            #
            # Each pairs a renewable credentials document with a static token file.
            # The document wins where both are configured: it can refresh itself,
            # while the plain file expires into a manual re-authorisation.
            atlassian_grants = {
                MCPBindingKind.NONE: (
                    settings.mcp_atlassian_credentials_file,
                    settings.mcp_atlassian_bearer_token_file,
                ),
                MCPBindingKind.JIRA: (
                    settings.atlassian_jira_credentials_file,
                    settings.atlassian_jira_token_file,
                ),
                MCPBindingKind.CONFLUENCE: (
                    settings.atlassian_confluence_credentials_file,
                    settings.atlassian_confluence_token_file,
                ),
            }
            bindings.extend(
                DevelopmentGrantBinding(
                    provider=MCPProvider.ATLASSIAN,
                    binding=binding_kind,
                    tenant_id=settings.mcp_atlassian_grant_tenant_id,
                    user_id=settings.mcp_atlassian_grant_user_id,
                    credentials_file=credentials_file,
                    token_endpoint=ATLASSIAN_TOKEN_ENDPOINT if credentials_file else None,
                    token_file=None if credentials_file else token_file,
                )
                for binding_kind, (credentials_file, token_file) in atlassian_grants.items()
                if credentials_file is not None or token_file is not None
            )
        figma_credentials = settings.mcp_figma_credentials_file
        figma_token = settings.mcp_figma_bearer_token_file
        if (
            (figma_credentials is not None or figma_token is not None)
            and settings.mcp_figma_grant_tenant_id is not None
            and settings.mcp_figma_grant_user_id is not None
        ):
            # Every Figma read is bound to the pinned file, so one key suffices. A
            # personal access token has nothing to refresh and arrives as a plain
            # token file; a renewable OAuth document supersedes it where configured,
            # as it does for Atlassian.
            bindings.append(
                DevelopmentGrantBinding(
                    provider=MCPProvider.FIGMA,
                    binding=MCPBindingKind.FIGMA,
                    tenant_id=settings.mcp_figma_grant_tenant_id,
                    user_id=settings.mcp_figma_grant_user_id,
                    credentials_file=figma_credentials,
                    token_endpoint=FIGMA_TOKEN_ENDPOINT if figma_credentials else None,
                    token_file=None if figma_credentials else figma_token,
                )
            )
        grant_broker = DevelopmentFileGrantBroker(
            environment=settings.environment,
            bindings=tuple(bindings),
        )
    else:
        grant_broker = UnavailableGrantBroker()

    transport = ProviderRoutedTransport(
        {
            MCPProvider.ATLASSIAN: SDKRemoteMCPTransport(grant_broker=grant_broker),
            MCPProvider.FIGMA: FigmaRESTTransport(
                grant_broker=grant_broker,
                credential_kind=settings.mcp_figma_credential_kind,
            ),
        }
    )
    return MCPReadWorkflow(
        settings=settings,
        registry=MCPToolRegistry(),
        transport=transport,
        audit_sink=audit_sink,
    )
