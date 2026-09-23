# Graph Report - PFE_M2  (2026-09-10)

## Corpus Check
- 227 files · ~180,068 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2770 nodes · 8247 edges · 146 communities (104 shown, 30 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 968 edges (avg confidence: 0.94)
- Token cost: 876,929 input · 0 output

## Community Hubs (Navigation)
- Approval In-Memory Store & Tests
- Read Citation Provenance
- MCP Read Orchestration & Figma REST
- Agent Stop Reasons & Audit Tests
- Agent Proposes-Writes Tests
- Mutation Registry & Contracts
- Source Permission Reauthorization
- Figma REST Adapter Tests
- Backend Config & Settings
- Markup Reduction
- OpenAI-Compatible LLM Adapter
- Development File Grant Broker
- Postgres Delegated Grant Store
- Groq Agent Tests
- MCP Remote Adapter & Figma Transport
- Approval Proposal Repository Adapters
- Gemini LLM Adapter
- Auth Domain & In-Memory Adapters
- MCP Read Command Domain
- Mutation Workflow & Approval Execution
- Atlassian Sign-In Tests
- Bootstrap & Application Container
- Approval API Routes
- Figma Frame Catalogue
- Mutation Approval & Security Docs
- HTTP Guard & Endpoint Pinning
- Mutation Gateway Tests
- RAG Retrieval Tests
- Tool Catalogue Filtering
- Database Readiness Schema
- Approval State Machine & Errors
- Auth Sign-In API
- NEXIA API Adapter (Frontend)
- MCP Registry & Identity
- Mutation Execute Route Tests
- Audit Sink Adapters
- Conversation History Tests
- Session Store Adapters
- App Entry & MCP API Tests
- NEXIA Chat UI
- Log Redaction
- Figma Catalogue Match Tests
- Frontend Package Dependencies
- MCP Remote Adapter Response Bound
- Semantic Embedding Store (Postgres)
- Semantic Index Digest Tests
- Mutation Gateway Core
- Server Session Tests
- Agent Audit Tests
- Approval Proposal Domain
- Semantic Indexing API
- Session & Conversation Postgres Adapters
- MCP Idempotency Store
- Local Embedding Provider
- Agent History Turns
- Agent API Tests
- Mutation Approval Preview UI
- Semantic Embedding Ports
- Frontend TypeScript Config
- LLM Provider Domain
- Atlassian OAuth Client
- Conversation API Routes
- Jira Seed Import Script
- MCP Grant Adapters
- MCP Contract Drift Tests
- CORS Origin Sign-In Tests
- Audited LLM Provider
- Conversation Domain Model
- Semantic Eval Script
- Conversation Repository Ports
- Knowledge Retrieval Domain
- MCP Read Tool Description
- CORS Tests
- Mutation Gateway Fake Session Tests
- Frontend Dev Dependencies
- Graphify Skill References
- Semantic Eval Helpers
- Agent Roles & Operating Model
- In-Memory Conversation Repository
- MCP Remote Error Mapping
- MCP Audit Fake Session Tests
- MCP-RO Architecture & Query Docs
- In-Memory Semantic Embedding Store
- Mutation Tool Pin Registry
- MCP Credentials Import Script
- Postgres Approval Unit of Work
- Health API
- Backend CI & Integration Report
- Frontend NPM Scripts
- HTTP Guard Byte Stream Limiter
- Shared Error Envelope
- MCP Read Result Domain
- Frontend App Layout & Config
- Deny-All Mutation Tool Pin
- Initial Persistence Migration
- API Test Stub Tool Pin
- Project Vision & Layering Docs
- MCP-RW & Roles Docs
- Groq LLM Adapter
- Mutation Gateway Internal Refusal
- Conversation History Migration
- Groq Fake Resolver Test
- Knowledge RAG Design Docs
- Coded Error Protocol
- Semantics Database Session
- Figma REST Stub Resolver
- Extraction Spec Rubric Docs
- Confluence Icon Concept
- Frontend Agent Rules Notices
- MCP Smoke Test Script
- Agent Adapters Package Init
- Approval Adapters Package Init
- Auth Package Init
- Conversation Adapters Package Init
- Figma Package Init
- Backend App Package Init
- MCP Ports Call Tool
- Sessions Package Init
- MCP Remote Adapter Exception
- RAG ACL Model Docs
- Knowledge Graph Migration Criteria
- Next.js Env Types
- Project Context Vision Notes
- Frontend Removal Guardrails
- Structuring Decisions Docs
- Figma Logo Icon
- Jira Logo Icon
- Link Icon
- Search Icon
- Send Icon
- Stars Icon (AI Indicator)
- Wand Icon (AI Sparkle)
- Welcome Hand Illustration
- Backend Pyproject Metadata

## God Nodes (most connected - your core abstractions)
1. `SecurityContext` - 161 edges
2. `Settings` - 111 edges
3. `MCPReadSourceSystem` - 103 edges
4. `ToolActionClass` - 74 edges
5. `MCPReadWorkflow` - 71 edges
6. `MCPProvider` - 69 edges
7. `AgentReadWorkflow` - 67 edges
8. `MCPBindingKind` - 64 edges
9. `ApprovalWorkflow` - 60 edges
10. `ActionProposal` - 51 edges

## Surprising Connections (you probably didn't know these)
- `Honesty Rules` --semantically_similar_to--> `Principes non négociables`  [INFERRED] [semantically similar]
  .claude/skills/graphify/SKILL.md → PROJECT_CONTEXT.md
- `Constrained query vocabulary expansion` --semantically_similar_to--> `AgentReadWorkflow orchestration loop`  [INFERRED] [semantically similar]
  .claude/skills/graphify/references/query.md → docs/development-logs/MCP-RO-ARCH-001.md
- `SystemeSemantique` --uses--> `LocalEmbeddingProvider`  [INFERRED]
  scripts/semantic_eval.py → backend/app/semantics/adapters/local_model.py
- `SystemeSemantique` --uses--> `InMemoryEmbeddingStore`  [INFERRED]
  scripts/semantic_eval.py → backend/app/semantics/adapters/memory.py
- `ReferenceLexicale` --uses--> `IndexableDocument`  [INFERRED]
  scripts/semantic_eval.py → backend/app/semantics/domain.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Eight-role agent operating team** — agents_architecte_tech_lead, agents_product_business_analyst, agents_frontend_ux, agents_backend_role, agents_ia_rag_knowledge_graph, agents_mcp_iam_securite, agents_qa_test_automation, agents_devops_sre [EXTRACTED 1.00]
- **Human-approval mutation chain (propose -> approve -> revalidate -> execute -> audit)** — docs_architecture_system_architecture_approval_policy_engine, docs_architecture_system_architecture_mcp_gateway, docs_development_logs_mcp_rw_001_mutation_registry, backend_readme_approvals_security, project_context_principes_non_negociables [INFERRED 0.85]
- **graphify build pipeline stages** — claude_skills_graphify_skill_step3_extraction, claude_skills_graphify_references_extraction_spec_node_id_format, claude_skills_graphify_references_query_vocab_expansion, claude_skills_graphify_references_update_incremental_update [EXTRACTED 1.00]
- **Approval State Machine Convergence Across Product/Security/QA** — docs_product_mvp_spec_approval_workflow, docs_security_mcp_security_design_approval_state_machine, docs_qa_test_strategy_approval_transitions [INFERRED 0.90]
- **Read-Only MCP Pilot Allowlist Implementation** — docs_security_mcp_security_design_allowlist_atlassian, docs_security_mcp_security_design_allowlist_figma, infra_compose_atlassian_bindings_document, infra_compose_figma_document [INFERRED 0.85]
- **SEC-* Requirement Traceability Across Design/Review/QA** — docs_security_backend_security_review_document, docs_security_mcp_security_design_document, docs_qa_test_strategy_document [EXTRACTED 1.00]

## Communities (146 total, 30 thin omitted)

### Community 0 - "Approval In-Memory Store & Tests"
Cohesion: 0.06
Nodes (74): InMemoryApprovalUnitOfWork, Callable factory sharing one serialized in-memory proposal/audit store., ActionDecision, ActionTarget, InMemoryConversationRepository, UUID, Development-only, process-local repository., Conversation (+66 more)

### Community 1 - "Read Citation Provenance"
Cohesion: 0.06
Nodes (62): AgentSource, _identity(), BaseModel, Turn read provenance into the sources an answer may claim. Two rules decide…, One performed read, as the loop observed it., What makes two reads the same source. A resource is identified by its reference…, Project reads into deduplicated sources, in the order they were first read.…, ReadRecord (+54 more)

### Community 2 - "MCP Read Orchestration & Figma REST"
Cohesion: 0.09
Nodes (46): The read orchestration loop: the model proposes, the registry decides. Sits…, BaseModel, Server-derived identity context; it must never be supplied by the LLM., SecurityContext, Retirer des journaux ce qui n'aurait jamais du y entrer. Le probleme est celui…, L'annuaire des frames Figma : retrouver un cadre par son nom, sans lien colle.…, Figma reads served by the Figma REST API behind the MCP read contract. Why this…, bound_response() (+38 more)

### Community 3 - "Agent Stop Reasons & Audit Tests"
Cohesion: 0.14
Nodes (59): AgentStopReason, StrEnum, InMemoryAuditSink, Any, Development-only audit sink. It is not a compliant durable audit log., agent_for(), answered(), ask() (+51 more)

### Community 4 - "Agent Proposes-Writes Tests"
Cohesion: 0.09
Nodes (57): a_call(), a_comment_call(), a_conversation(), a_question(), a_response(), _Named, Any, anyio (+49 more)

### Community 5 - "Mutation Registry & Contracts"
Cohesion: 0.05
Nodes (53): _borne(), _diff_for(), Ce que l'ecriture changera, dit assez precisement pour qu'on puisse…, MCPMutationRegistry, MutationToolContract, Un outil d'ecriture approuve, avec les deux schemas qui l'encadrent.…, Les ecritures declarees, indexees par (systeme, nom d'outil). Vide est un etat…, Une troncature invisible ferait approuver un changement dont on ne montre qu'un… (+45 more)

### Community 6 - "Source Permission Reauthorization"
Cohesion: 0.09
Nodes (45): _identifiers_in(), _payload_of(), Any, Reauthorise a write by reading its target, immediately before writing it. The…, The provider's own JSON, out of the normalised content blocks., The version string the source states for a resource it just returned. Kept…, Every id and key in a listing, flattened, as strings. The two products disagree…, Confirms a write's target by reading it through the ordinary read pipeline. (+37 more)

### Community 7 - "Figma REST Adapter Tests"
Cohesion: 0.09
Nodes (42): _api_node_id(), _build_process(), _collect(), _endpoint_id(), FigmaRESTSession, Any, AsyncClient, The text a FigJam shape carries, wherever the API chose to put it. (+34 more)

### Community 8 - "Backend Config & Settings"
Cohesion: 0.06
Nodes (44): get_settings(), _is_loopback(), model_validator, Path, True only for the local machine, by name or by address. ``localhost`` is…, An empty string is how a container says "not set", so read it that way. Compose…, HTTPS everywhere, with one narrow exception for a developer machine. An…, Token file serving the Jira binding: its override, else the provider file. (+36 more)

### Community 9 - "Markup Reduction"
Cohesion: 0.06
Nodes (45): looks_like_markup(), Reduce source markup to the text a human would actually have seen. Runs before…, Return what a reader would have seen, or the text unchanged if it is prose., reduce_markup(), _Reducer, neutralise(), Confinement of source content before it reaches the model. The read loop…, Make template markers and envelope look-alikes inert, keeping the text. (+37 more)

### Community 10 - "OpenAI-Compatible LLM Adapter"
Cohesion: 0.11
Nodes (41): OpenAICompatibleLLMProvider, Any, AsyncClient, The chat-completions shape, shared by every provider that speaks it. Groq and…, Drop any <think> block a model wrote into the answer despite the request. The…, Rebuild the model's tool calls, treating every field as untrusted input.…, Chat completions against a pinned endpoint. The API key never leaves here.…, Pin and validate the destination when the subclass module is imported. Here… (+33 more)

### Community 11 - "Development File Grant Broker"
Cohesion: 0.08
Nodes (41): DevelopmentFileGrantBroker, DevelopmentGrantBinding, Development-only broker that rereads its mounted grant for each connection., One development grant: either a static token, or a credentials document. A…, _acquire(), _credentials_broker(), _FakeAsyncClient, _FakeResponse (+33 more)

### Community 12 - "Postgres Delegated Grant Store"
Cohesion: 0.08
Nodes (32): _advisory_key(), PostgresDelegatedGrantStore, DatabaseSession, sessionmaker, The grant, renewed first if it is close to lapsing. ``renew`` performs the…, Delegated Atlassian grants, encrypted at rest and renewed under a lock. The…, _associated_data(), GrantCipher (+24 more)

### Community 13 - "Groq Agent Tests"
Cohesion: 0.19
Nodes (46): api_key_file(), completion(), json_handler(), provider_for(), Any, anyio, Exception, LogCaptureFixture (+38 more)

### Community 14 - "MCP Remote Adapter & Figma Transport"
Cohesion: 0.12
Nodes (33): AbstractAsyncContextManager, _build_mcp_read_workflow(), FigmaRESTTransport, Read-only Figma transport. Credentials never leave this adapter., BearerGrant, DelegatedGrantBroker, Protocol, Ephemeral adapter-only grant material. Its representation never contains the… (+25 more)

### Community 15 - "Approval Proposal Repository Adapters"
Cohesion: 0.09
Nodes (20): InMemoryActionProposalRepository, _InMemoryApprovalTransaction, Any, BaseException, Self, TracebackType, UUID, Development-only repository with atomic optimistic transitions per process. (+12 more)

### Community 16 - "Gemini LLM Adapter"
Cohesion: 0.11
Nodes (41): GeminiLLMProvider, Gemini, through its OpenAI-compatible surface, on the shared socle. Google…, Chat completions against a pinned Gemini endpoint. The API key never leaves…, api_key_file(), completion_with(), FakeResolver, provider_for(), Any (+33 more)

### Community 17 - "Auth Domain & In-Memory Adapters"
Cohesion: 0.08
Nodes (27): InMemoryDelegatedGrantSink, InMemoryPendingAuthorizationStore, Holds delegated credentials in process memory, and never on disk. Stands in…, Process-local in-flight sign-ins. Adequate for a single process: a pending…, AtlassianSite, DelegatedCredentials, new_code_verifier(), new_state() (+19 more)

### Community 18 - "MCP Read Command Domain"
Cohesion: 0.14
Nodes (43): MCPReadCommand, MCPReadSourceSystem, A caller-selected read tool. Provider bindings are never accepted here., enabled_settings(), Any, MonkeyPatch, parametrize, 2025-11-25 is the highest revision the Atlassian MCP server speaks. (+35 more)

### Community 19 - "Mutation Workflow & Approval Execution"
Cohesion: 0.08
Nodes (31): ApprovedMutationRunner, UUID, Fail-closed mutation façade enforcing approval and source reauthorization.…, Move the proposal one state on, with its explanation, in one transaction., InvalidTransition, ProposalExpired, The approval window closed before the decision or the execution arrived., ApprovalUnitOfWork (+23 more)

### Community 20 - "Atlassian Sign-In Tests"
Cohesion: 0.14
Nodes (39): anyio_backend(), app_with_sign_in(), anyio, fixture, Play the first leg, then hand back the state the provider would return., A transport standing in for Atlassian, remembering what it was sent., Atlassian sends a signed JWT, not a short opaque handle. The first real…, A refusal must not hand the credential back to the browser. FastAPI reports a… (+31 more)

### Community 21 - "Bootstrap & Application Container"
Cohesion: 0.11
Nodes (36): PostgresApprovalUnitOfWorkFactory, ApplicationContainer, _build_agent(), build_container(), _build_frame_catalogue(), _build_grant_sink(), _build_llm_provider(), _build_mutations() (+28 more)

### Community 22 - "Approval API Routes"
Cohesion: 0.13
Nodes (37): approve_action_proposal(), create_action_proposal(), execute_action_proposal(), get_action_proposal(), get_mutations(), get_workflow(), Depends, get (+29 more)

### Community 23 - "Figma Frame Catalogue"
Cohesion: 0.07
Nodes (28): FigmaFrameCatalogue, _first_json(), FrameEntry, _normalise(), Any, Retrouve un cadre par son nom parmi les fichiers que le deploiement designe. Se…, Les maquettes indexees, telles qu'on peut les nommer au modele. Rend le nom…, Chercher, et relire les maquettes si rien ne correspond. La relecture n'a lieu… (+20 more)

### Community 24 - "Mutation Approval & Security Docs"
Cohesion: 0.07
Nodes (39): Mutation Approval State Machine (Product), Confluence-first then Jira Copy Flow, MVP Product Specification, OUT_OF_SYNC Detection, RAG as Derived, Reconstructible Index, Approval Transition Table (QA), Defect Severity Classification (S0-S3), MVP Test Strategy (+31 more)

### Community 25 - "HTTP Guard & Endpoint Pinning"
Cohesion: 0.07
Nodes (27): AsyncBaseTransport, Path, AsyncBaseTransport, bounded_response_hook(), EndpointResolver, is_approved_public_address(), PinnedAddressTransport, AsyncBaseTransport (+19 more)

### Community 26 - "Mutation Gateway Tests"
Cohesion: 0.16
Nodes (34): a_call(), a_session(), execute(), FakeBlock, gateway_for(), Le transport d'une ecriture approuvee. Le sujet central de ce fichier est la…, Injecte cote serveur apres l'approbation : c'est ce qui garantit qu'une…, Le schema public est ferme et ne declare pas cloudId, donc la tentative echoue… (+26 more)

### Community 27 - "RAG Retrieval Tests"
Cohesion: 0.14
Nodes (28): anyio_backend(), CollectingAudit, context(), piste(), fixture, question(), Retrieval feeding the orchestration loop. The property under test is not "does…, Framing is the control here, not decoration. The system prompt already states… (+20 more)

### Community 28 - "Tool Catalogue Filtering"
Cohesion: 0.11
Nodes (30): _index_by_tool_name(), _mutation_catalogue(), Describe the approved reads to the model, from public schemas only.…, Les ecritures declarees, presentees au modele comme des outils ordinaires. Le…, Map a bare tool name back to its contract, and refuse an ambiguous one. The…, tool_catalogue(), _offered_systems(), Les connecteurs qu'il est honnete de proposer au modele. Derive des memes… (+22 more)

### Community 29 - "Database Readiness Schema"
Cohesion: 0.09
Nodes (26): database_is_ready(), expected_schema_revisions(), Engine, Path, Les revisions de tete que le code de cette image attend. Lues dans le…, Joignable ET au bon schema. Le second controle manquait, et son absence n'etait…, Contre une vraie base, parce que le defaut d'origine venait precisement d'un…, La preuve la plus directe : on falsifie la version appliquee et la sonde doit… (+18 more)

### Community 30 - "Approval State Machine & Errors"
Cohesion: 0.13
Nodes (18): ActionProposalState, StrEnum, sha256_text(), InvalidDecisionToken, ProposalConversationNotFound, UUID, A mutation was proposed from an identity no sign-in stands behind. Named rather…, SessionRequired (+10 more)

### Community 31 - "Auth Sign-In API"
Cohesion: 0.10
Nodes (30): complete_sign_in(), _cookie_is_secure(), get_sign_in(), alias, Cookie, get, post, Query (+22 more)

### Community 32 - "NEXIA API Adapter (Frontend)"
Cohesion: 0.14
Nodes (29): approvalTarget(), approveActionProposal(), askQuestion(), ConversationResponse, createActionProposal(), createConversation(), decideActionProposal(), executeActionProposal() (+21 more)

### Community 33 - "MCP Registry & Identity"
Cohesion: 0.11
Nodes (20): Ce a quoi une proposition de mutation est epinglee. L'empreinte dit quelle…, _from_session(), _no_identity(), HTTPException, Request, Derive the identity from a server-held session, or refuse. The identity headers…, _unsupported_mode(), Le transport d'une ecriture approuvee, et rien d'autre. Cette passerelle est le… (+12 more)

### Community 34 - "Mutation Execute Route Tests"
Cohesion: 0.14
Nodes (27): client_for(), execute(), Any, Exception, parametrize, TestClient, La route qui depense une approbation. Deux proprietes valent le fichier a elles…, La propriete la plus importante du fichier. L'appel est parti et rien n'est… (+19 more)

### Community 35 - "Audit Sink Adapters"
Cohesion: 0.12
Nodes (13): Fail-closed audit around any language model provider. Written as a decorator…, PostgresAppendOnlyAuditWriter, PostgresAuditSink, sessionmaker, Persists one event per short autonomous transaction, never around I/O., Appends audit events through the approval transaction's Session., AuditEvent, BaseModel (+5 more)

### Community 36 - "Conversation History Tests"
Cohesion: 0.24
Nodes (26): a_conversation(), an_answer(), ask(), client_for(), Any, Exception, TestClient, Le defaut que cette tranche corrige, vu depuis la route. Les tours etaient… (+18 more)

### Community 37 - "Session Store Adapters"
Cohesion: 0.11
Nodes (12): sessionmaker, sessionmaker, InMemorySessionStore, Development-only, process-local session store., BaseModel, datetime, One signed-in identity, held by the server and named by an opaque token., Session (+4 more)

### Community 38 - "App Entry & MCP API Tests"
Cohesion: 0.12
Nodes (24): create_app(), lifespan(), build_client(), Path, TestClient, test_conversation_is_visible_only_to_its_owner(), test_health_endpoints_are_available(), test_postgres_readiness_fails_closed_within_health_budget() (+16 more)

### Community 39 - "NEXIA Chat UI"
Cohesion: 0.09
Nodes (12): NexiaAnswer, nexiaApi, NexiaGateway, ChatMessage, messageId(), NexiaChat(), handleSubmit(), NexiaChatProps (+4 more)

### Community 40 - "Log Redaction"
Cohesion: 0.11
Nodes (24): install_log_redaction(), Poser le filtre, une fois, sur les journaux concernes. Idempotent parce que…, Remplacer la valeur des parametres sensibles, en gardant le reste lisible. Le…, Reecrit un enregistrement avant qu'il n'atteigne le moindre gestionnaire. Agit…, redact(), RedactSensitiveQueryParameters, parametrize, Le code d'autorisation OAuth ne doit pas survivre dans les journaux. Le rappel… (+16 more)

### Community 41 - "Figma Catalogue Match Tests"
Cohesion: 0.13
Nodes (23): catalogue_for(), Any, anyio, Exception, Si un cadre porte exactement le nom demande, ajouter tous ceux qui contiennent…, Le comportement qui rend l'annuaire utilisable : l'utilisateur ajoute un cadre…, Une faute de frappe suffirait sinon a faire relire toutes les maquettes a…, Un chemin de lecture parallele ferait sortir du contenu Figma sans qu'aucun… (+15 more)

### Community 42 - "Frontend Package Dependencies"
Cohesion: 0.09
Nodes (22): dependencies, next, react, react-dom, name, private, version, NexiaApproval (+14 more)

### Community 43 - "MCP Remote Adapter Response Bound"
Cohesion: 0.16
Nodes (19): Bound a response at the shared MCP wire ceiling., reject_oversized_response(), SDKMCPReadSession, MCPProtocolRejected, Any, StubSDKClient, test_chunked_wire_response_is_bounded_without_content_length(), test_compressed_wire_response_is_refused_before_body_read() (+11 more)

### Community 44 - "Semantic Embedding Store (Postgres)"
Cohesion: 0.15
Nodes (14): PostgresEmbeddingStore, Vectors in the same database as everything else, via pgvector., IndexableDocument, BaseModel, datetime, A source document reduced to what gets embedded, plus how to find it again., Title and body as one passage. Embedded together rather than separately: a Jira…, One embedded document as it lives in the database. (+6 more)

### Community 45 - "Semantic Index Digest Tests"
Cohesion: 0.15
Nodes (21): content_digest(), What was embedded, and by which model. The model name is part of the digest on…, document(), index_for(), The semantic slice, tested without ever loading a model. A real embedding model…, A digest over the text alone would make a model change invisible. Every…, Otherwise every "what looks like this?" answer starts with the question., Deterministic vectors, plus a record of what it was asked to embed. (+13 more)

### Community 46 - "Mutation Gateway Core"
Cohesion: 0.17
Nodes (16): _external_ids(), _first_json_block(), MCPMutationGateway, Any, Valider la surface publique, puis injecter le liant, puis revalider. Deux…, Le fournisseur a traite la demande et l'a refusee. C'est une issue CONNUE, pas…, Conclure a partir de ce que le fournisseur a renvoye. Arriver ici signifie que…, Un refus prononce avant que le fournisseur soit contacte. Rendu et non leve :… (+8 more)

### Community 47 - "Server Session Tests"
Cohesion: 0.18
Nodes (22): new_session_token(), What the store holds instead of the token itself. A leaked database must not…, session_token_hash(), Exception, Base class for identity failures the request path must answer., The store could not be consulted, so no identity can be asserted., SessionError, SessionUnavailable (+14 more)

### Community 48 - "Agent Audit Tests"
Cohesion: 0.27
Nodes (21): a_request(), a_response(), audited(), BrokenSink, Any, run(), test_a_bounded_call_records_the_ceiling_it_hit(), test_a_successful_call_is_authorized_then_completed() (+13 more)

### Community 49 - "Approval Proposal Domain"
Cohesion: 0.13
Nodes (15): ActionProposalCreate, canonical_hash(), canonical_json(), _named_in(), Any, datetime, model_validator, Self (+7 more)

### Community 50 - "Semantic Indexing API"
Cohesion: 0.12
Nodes (19): get_indexer(), BaseModel, Depends, post, Request, Bring this tenant's index in step with its Jira project. The JQL comes from the…, reindex(), ReindexResult (+11 more)

### Community 51 - "Session & Conversation Postgres Adapters"
Cohesion: 0.13
Nodes (10): PostgresConversationMessageRepository, UUID, Durable turns, written as one transaction per exchange turn., PersistenceMappingError, RuntimeError, Safe error raised when stored data violates a domain contract., PostgresSessionStore, DatabaseSession (+2 more)

### Community 52 - "MCP Idempotency Store"
Cohesion: 0.17
Nodes (9): _mint(), PostgresMutationIdempotencyStore, sessionmaker, UUID, Durable reservation, committed on its own before the provider is contacted. It…, MutationReservation, UUID, The single idempotency key an approved proposal may ever be executed under. (+1 more)

### Community 53 - "Local Embedding Provider"
Cohesion: 0.14
Nodes (14): LocalEmbeddingProvider, Any, TextKind, multilingual-e5-base, running in this process. Local rather than a hosted…, prefixed(), TextKind, Apply the instruction prefix the model was trained with., EmbeddingBackendUnavailable (+6 more)

### Community 54 - "Agent History Turns"
Cohesion: 0.17
Nodes (19): _prior_turns(), UUID, Record one turn, and never let that recording sink the exchange. Deliberately…, Les tours passes, tels que le modele les reverra. Les tours en erreur sont…, _record(), PriorTurn, Un tour passe, rejoue au modele. Volontairement reduit a un role et un texte.…, MessageRole (+11 more)

### Community 55 - "Agent API Tests"
Cohesion: 0.24
Nodes (17): AgentAnswer, ask(), client_for(), Any, Exception, parametrize, Path, TestClient (+9 more)

### Community 56 - "Mutation Approval Preview UI"
Cohesion: 0.15
Nodes (17): NexiaMutationExecution, NexiaMutationProposalState, actionLabel(), ApprovalUiState, errorState(), expiresInMinutes(), isTerminal(), MutationApprovalPreview() (+9 more)

### Community 57 - "Semantic Embedding Ports"
Cohesion: 0.12
Nodes (12): EmbeddingProvider, EmbeddingStore, Protocol, TextKind, Embed a batch, applying the model's instruction prefix for ``kind``. Batched…, Where vectors live, always scoped to one tenant., External id to stored content digest, for deciding what needs re-embedding., The closest documents in this tenant, nearest first. ``exclude_external_id``… (+4 more)

### Community 58 - "Frontend TypeScript Config"
Cohesion: 0.11
Nodes (18): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+10 more)

### Community 59 - "LLM Provider Domain"
Cohesion: 0.16
Nodes (10): LLMProvider, LLMRequest, LLMResponse, BaseModel, Protocol, Provider-neutral LLM contract. The Groq client belongs in an adapter.…, Public interface of the agent orchestration module., Exception (+2 more)

### Community 60 - "Atlassian OAuth Client"
Cohesion: 0.25
Nodes (9): AtlassianOAuthClient, Any, AsyncClient, Response, The site whose cloud id becomes the tenant, or a refusal. Nothing in a…, Resolve once, approve, and connect to that address. Connecting by hostname…, The three outbound calls a sign-in makes, under the project's transport rules.…, ProviderRefused (+1 more)

### Community 61 - "Conversation API Routes"
Cohesion: 0.18
Nodes (16): create_conversation(), get_conversation(), get_workflow(), list_conversation_messages(), Depends, get, post, Query (+8 more)

### Community 62 - "Jira Seed Import Script"
Cohesion: 0.20
Nodes (17): _adf(), _appel(), _autorisation(), _charger_le_registre(), _ecrire_le_registre(), ImportEchoue, main(), Any (+9 more)

### Community 63 - "MCP Grant Adapters"
Cohesion: 0.21
Nodes (8): Any, Path, A delegated OAuth document on disk that renews itself before it expires. The…, Reject anything that is not a plausible bearer token, without echoing it., RenewableCredentialsFile, UnavailableGrantBroker, _validated_token(), MCPGrantUnavailable

### Community 64 - "MCP Contract Drift Tests"
Cohesion: 0.17
Nodes (14): schema_sha256(), The drift check only means something if the two declarations are kept apart.…, test_the_published_manifest_matches_every_registry_contract(), Le defaut que ce test ferme. ``_semantic_schema`` retirait toute cle nommee…, Le pendant : l'annotation reste ignoree, sinon chaque reformulation de prose…, Une propriete nommee comme un mot-cle, imbriquee sous une autre., test_a_property_named_description_is_covered_by_the_fingerprint(), test_changing_the_type_of_such_a_property_changes_the_fingerprint() (+6 more)

### Community 65 - "CORS Origin Sign-In Tests"
Cohesion: 0.15
Nodes (16): parametrize, The point of the change: a front end on another port can be returned to. No new…, The common case, and the only one a same-origin deployment needs., http://localhost:3000@elsewhere.example navigates to elsewhere.example. It…, An empty allow list allows nothing, rather than everything., registered(), test_a_path_remains_accepted_and_needs_no_listed_origin(), test_a_plain_http_callback_is_refused_off_the_loopback_host() (+8 more)

### Community 66 - "Audited LLM Provider"
Cohesion: 0.19
Nodes (11): AuditedLLMProvider, _prompt_fingerprint(), Any, Identify a prompt without storing it. Sorted keys so that two structurally…, An ``LLMProvider`` that cannot be called without leaving a trace., AuditEventType, StrEnum, parametrize (+3 more)

### Community 67 - "Conversation Domain Model"
Cohesion: 0.23
Nodes (10): CitedSource, ConversationCreate, BaseModel, datetime, One source an answer cited, as the read workflow observed it. A projection of…, utc_now(), ConversationNotFound, UUID (+2 more)

### Community 68 - "Semantic Eval Script"
Cohesion: 0.22
Nodes (6): Counter, _mots(), Le modele reel, derriere le meme protocole de mesure., TF-IDF et cosinus, sans dependance ni modele. Ce n'est pas un homme de paille :…, ReferenceLexicale, SystemeSemantique

### Community 69 - "Conversation Repository Ports"
Cohesion: 0.21
Nodes (7): ConversationMessageRepository, ConversationRepository, Protocol, UUID, Durable conversation turns. Separate from ``ConversationRepository`` because…, ConversationWorkflow, Owns conversation creation, turn recording and tenant/owner visibility rules.

### Community 70 - "Knowledge Retrieval Domain"
Cohesion: 0.30
Nodes (10): KnowledgePassage, KnowledgeQuery, BaseModel, StrEnum, RetrievalIntent, SourceProvenance, Public interface of the knowledge retrieval module., KnowledgeRetriever (+2 more)

### Community 71 - "MCP Read Tool Description"
Cohesion: 0.22
Nodes (7): RemoteContentBlock, RemoteToolDescription, RemoteToolResult, SpySession, SpyTransport, test_image_size_and_mime_are_validated(), test_text_and_structured_size_limit_is_enforced()

### Community 72 - "CORS Tests"
Cohesion: 0.22
Nodes (13): client_for(), parametrize, TestClient, CORS is what lets the browser front end reach this API at all -- and what a…, test_a_declared_origin_is_granted(), test_a_local_https_front_end_is_accepted(), test_an_origin_that_is_not_an_exact_safe_origin_is_refused(), test_another_origin_is_not_granted() (+5 more)

### Community 73 - "Mutation Gateway Fake Session Tests"
Cohesion: 0.18
Nodes (7): FakeRemoteResult, FakeSession, FakeTool, FakeTransport, Any, Exception, Calque sur ``RemoteToolResult``, qui ne porte QUE ces deux champs. Une version…

### Community 74 - "Frontend Dev Dependencies"
Cohesion: 0.14
Nodes (14): devDependencies, eslint, eslint-config-next, jsdom, @testing-library/jest-dom, @testing-library/react, @testing-library/user-event, @types/node (+6 more)

### Community 75 - "Graphify Skill References"
Cohesion: 0.15
Nodes (13): .claude/CLAUDE.md (graphify trigger), Root CLAUDE.md graphify rules, /graphify add <url>, --watch (background rebuild), graphify MCP server, Neo4j / FalkorDB export, Cross-repo / monorepo merge, graphify claude install (CLAUDE.md integration) (+5 more)

### Community 76 - "Semantic Eval Helpers"
Cohesion: 0.29
Nodes (12): afficher(), charger_le_corpus(), evaluer(), _lignes(), main(), mesurer_les_doublons(), mesurer_les_requetes(), Any (+4 more)

### Community 77 - "Agent Roles & Operating Model"
Cohesion: 0.18
Nodes (12): Architecte / Tech Lead (role), Backend (role), Definition of Done (AGENTS.md), DevOps / SRE (role), Frontend / UX (role), IA / RAG / Knowledge Graph (role), Notion bases (Specs/Tasks/Decisions/Development Log), Product / Business Analyst (role) (+4 more)

### Community 78 - "In-Memory Conversation Repository"
Cohesion: 0.24
Nodes (6): InMemoryConversationMessageRepository, Development-only, process-local turn store., ConversationMessage, One turn of a conversation, owned by a tenant and by its author., UUID, Record one turn, after proving the caller owns the thread. The ownership check…

### Community 79 - "MCP Remote Error Mapping"
Cohesion: 0.27
Nodes (8): _contains_across_byte_fragments(), _contains_across_text_fragments(), _iter_leaf_exceptions(), _map_transport_exception(), Any, BaseException, Map an SDK failure onto the MCP error taxonomy, flattening exception groups.…, _structured_text_fragments()

### Community 80 - "MCP Audit Fake Session Tests"
Cohesion: 0.20
Nodes (5): FakeSession, FakeSessionFactory, FakeTransaction, BaseException, TracebackType

### Community 81 - "MCP-RO Architecture & Query Docs"
Cohesion: 0.20
Nodes (11): POST /api/mcp/reads (read-only MCP endpoint), BFS/DFS traversal modes, Constrained query vocabulary expansion, Sprint 0 security verdict (NO-GO for MCP mutations), Agent Orchestrator, MCP Gateway, AgentReadWorkflow orchestration loop, Figma catalogue block -> REST API switch (+3 more)

### Community 82 - "In-Memory Semantic Embedding Store"
Cohesion: 0.20
Nodes (6): cosine_distance(), InMemoryEmbeddingStore, Vectors in a dictionary. For tests and for a build with no database., The same measure pgvector applies, for stores that have no database., Zero is identical, one is orthogonal, and it is never rescaled. The citations…, test_the_distance_is_a_distance_and_not_a_score()

### Community 83 - "Mutation Tool Pin Registry"
Cohesion: 0.22
Nodes (7): Lit l'empreinte dans le registre des mutations. Refuse par defaut : un outil…, RegistryMutationToolPin, Refus par defaut. Inventer une empreinte laisserait une proposition revendiquer…, Le nom existe dans l'autre registre, ce qui ne lui donne aucun droit ici., test_a_read_tool_has_no_mutation_pin(), test_the_pin_denies_an_undeclared_tool(), test_the_pin_resolves_a_declared_tool()

### Community 84 - "MCP Credentials Import Script"
Cohesion: 0.33
Nodes (8): _covered_sites(), _latest_store(), main(), _parse_arguments(), Path, Construit un document de credentials MCP a partir du cache de mcp-remote. `mcp-…, Les sites Atlassian que ce jeton couvre, ou None si ce n'en est pas un. Cet…, Le couple (tokens, client_info) le plus recent du cache mcp-remote. Le cache…

### Community 85 - "Postgres Approval Unit of Work"
Cohesion: 0.25
Nodes (4): PostgresApprovalUnitOfWork, BaseException, Self, TracebackType

### Community 86 - "Health API"
Cohesion: 0.50
Nodes (7): health(), HealthResponse, liveness(), BaseModel, get, Request, _readiness()

### Community 87 - "Backend CI & Integration Report"
Cohesion: 0.33
Nodes (7): Approval token security (one-time 256-bit), PKA_ environment configuration, Sprint 1 recommended order, CHAT-BE-PG-001: PostgreSQL persistence for backend, backend CI workflow, pgvector/pgvector:pg16 CI service, two-pass pytest (unit before integration)

### Community 88 - "Frontend NPM Scripts"
Cohesion: 0.29
Nodes (7): scripts, build, dev, lint, start, test, typecheck

### Community 89 - "HTTP Guard Byte Stream Limiter"
Cohesion: 0.33
Nodes (3): AsyncByteStream, LimitedAsyncByteStream, Stops a response body at a byte ceiling as it streams, before it is buffered.

### Community 90 - "Shared Error Envelope"
Cohesion: 0.33
Nodes (6): ErrorEnvelope, ErrorResponse, BaseModel, The body of every failure this API produces., One shape everywhere, so a client writes one error handler and not five., test_every_documented_failure_carries_the_shared_envelope()

### Community 91 - "MCP Read Result Domain"
Cohesion: 0.47
Nodes (4): MCPReadResult, Any, Exception, _result()

### Community 92 - "Frontend App Layout & Config"
Cohesion: 0.33
Nodes (3): nextConfig, metadata, next

### Community 93 - "Deny-All Mutation Tool Pin"
Cohesion: 0.40
Nodes (4): NoMutationToolsPin, Refuse chaque outil de mutation. Conserve apres l'arrivee du registre, pour les…, Conserve pour les deploiements sans surface d'ecriture., test_the_denying_pin_still_denies_everything()

### Community 94 - "Initial Persistence Migration"
Cohesion: 0.40
Nodes (4): downgrade(), Refuse an automatic data-destructive rollback., Add pgvector and the first durable, tenant-scoped tables., upgrade()

### Community 95 - "API Test Stub Tool Pin"
Cohesion: 0.50
Nodes (3): Stands in for the mutation registry, which does not exist yet: the production…, StubToolPin, test_action_decision_token_is_returned_once_and_never_by_get()

### Community 96 - "Project Vision & Layering Docs"
Cohesion: 0.50
Nodes (5): Honesty Rules, Backend layered structure (domain/ports/workflow/adapters/bootstrap), Principes non négociables, Project Vision (chat assistant over Jira/Confluence/Figma), Project Knowledge Assistant (README)

### Community 97 - "MCP-RW & Roles Docs"
Cohesion: 0.50
Nodes (4): MCP / IAM / Sécurité (role), Approval Policy Engine, Six defects found via real E2E trials, MCP-RW-001: mutation_registry.py (write approval chain)

### Community 98 - "Groq LLM Adapter"
Cohesion: 0.50
Nodes (3): GroqLLMProvider, Groq, on the shared chat-completions socle. Everything about the wire --…, Chat completions against a pinned Groq endpoint. The API key never leaves here.

### Community 99 - "Mutation Gateway Internal Refusal"
Cohesion: 0.50
Nodes (3): Exception, Interne au module : porte un code jusqu'au point qui sait le rendre., _Refusal

### Community 102 - "Knowledge RAG Design Docs"
Cohesion: 0.50
Nodes (4): retrieval_queries_gold.csv (piege_attendu), SEED-01..30 synthetic Jira ticket corpus, semantic_pairs_gold.csv, Ingestion pipeline (MCP -> normalize -> fragment -> embed)

### Community 103 - "Coded Error Protocol"
Cohesion: 0.67
Nodes (3): CodedError, Protocol, Errors that already carry their own identifier and safe wording.

### Community 111 - "Extraction Spec Rubric Docs"
Cohesion: 0.67
Nodes (3): Confidence score rubric, Node ID format rule, Step 3 - Structural + Semantic Extraction

### Community 112 - "Confluence Icon Concept"
Cohesion: 0.67
Nodes (3): Figma Assets Integration Icon Set, Confluence Icon, Atlassian Confluence

## Ambiguous Edges - Review These
- `Defect Severity Classification (S0-S3)` → `Backend Security Review (Scaffold)`  [AMBIGUOUS]
  docs/qa/test-strategy.md · relation: conceptually_related_to

## Knowledge Gaps
- **119 isolated node(s):** `project-knowledge-assistant-backend`, `nextConfig`, `name`, `version`, `private` (+114 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 953 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **30 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Defect Severity Classification (S0-S3)` and `Backend Security Review (Scaffold)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `SecurityContext` connect `MCP Read Orchestration & Figma REST` to `Approval In-Memory Store & Tests`, `Read Citation Provenance`, `Agent Stop Reasons & Audit Tests`, `Agent Proposes-Writes Tests`, `Source Permission Reauthorization`, `Figma REST Adapter Tests`, `OpenAI-Compatible LLM Adapter`, `Development File Grant Broker`, `Groq Agent Tests`, `MCP Remote Adapter & Figma Transport`, `Gemini LLM Adapter`, `MCP Read Command Domain`, `Mutation Workflow & Approval Execution`, `Bootstrap & Application Container`, `Approval API Routes`, `Figma Frame Catalogue`, `Mutation Gateway Tests`, `RAG Retrieval Tests`, `Approval State Machine & Errors`, `MCP Registry & Identity`, `Audit Sink Adapters`, `MCP Remote Adapter Response Bound`, `Mutation Gateway Core`, `Agent Audit Tests`, `Semantic Indexing API`, `Agent History Turns`, `LLM Provider Domain`, `Conversation API Routes`, `MCP Grant Adapters`, `Audited LLM Provider`, `Conversation Domain Model`, `Conversation Repository Ports`, `Knowledge Retrieval Domain`, `MCP Read Tool Description`, `In-Memory Conversation Repository`, `MCP Remote Error Mapping`?**
  _High betweenness centrality (0.111) - this node is a cross-community bridge._
- **Why does `Settings` connect `Backend Config & Settings` to `MCP Read Orchestration & Figma REST`, `Mutation Registry & Contracts`, `Development File Grant Broker`, `Groq Agent Tests`, `MCP Remote Adapter & Figma Transport`, `Gemini LLM Adapter`, `MCP Read Command Domain`, `Mutation Workflow & Approval Execution`, `Atlassian Sign-In Tests`, `Bootstrap & Application Container`, `Mutation Gateway Tests`, `Tool Catalogue Filtering`, `MCP Registry & Identity`, `Mutation Execute Route Tests`, `Conversation History Tests`, `App Entry & MCP API Tests`, `Log Redaction`, `Mutation Gateway Core`, `Server Session Tests`, `Agent API Tests`, `MCP Contract Drift Tests`, `CORS Origin Sign-In Tests`, `CORS Tests`, `API Test Stub Tool Pin`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Why does `MCPReadSourceSystem` connect `MCP Read Command Domain` to `Read Citation Provenance`, `MCP Read Orchestration & Figma REST`, `Agent Stop Reasons & Audit Tests`, `Agent Proposes-Writes Tests`, `Mutation Registry & Contracts`, `Source Permission Reauthorization`, `MCP Remote Adapter & Figma Transport`, `Bootstrap & Application Container`, `Figma Frame Catalogue`, `Mutation Gateway Tests`, `Tool Catalogue Filtering`, `MCP Registry & Identity`, `Conversation History Tests`, `Agent Audit Tests`, `MCP Contract Drift Tests`, `Audited LLM Provider`, `MCP Read Tool Description`, `Mutation Tool Pin Registry`, `MCP Read Result Domain`, `Deny-All Mutation Tool Pin`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Are the 44 inferred relationships involving `SecurityContext` (e.g. with `OpenAICompatibleLLMProvider` and `answer_question()`) actually correct?**
  _`SecurityContext` has 44 INFERRED edges - model-reasoned connections that need verification._
- **Are the 28 inferred relationships involving `Settings` (e.g. with `ApplicationContainer` and `_build_agent()`) actually correct?**
  _`Settings` has 28 INFERRED edges - model-reasoned connections that need verification._
- **Are the 80 inferred relationships involving `MCPReadSourceSystem` (e.g. with `AgentSource` and `AgentReadWorkflow`) actually correct?**
  _`MCPReadSourceSystem` has 80 INFERRED edges - model-reasoned connections that need verification._