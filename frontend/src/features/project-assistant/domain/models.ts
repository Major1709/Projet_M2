// "atlassian" is not a fourth product: it is what the backend reports when a read
// went through the Atlassian MCP server without the tool telling which of Jira or
// Confluence answered. Narrowing it to one of the two would name a product nobody
// verified, so the union carries it as it comes.
export type SourceSystem = "atlassian" | "jira" | "confluence" | "figma";

export type JiraStatus = "À qualifier" | "En analyse" | "Prête" | "Bloquée";

export type IndexationState = "NOT_INDEXED" | "QUEUED" | "INDEXING" | "INDEXED" | "FAILED";

export type MessageRole = "user" | "assistant" | "system";

export type ActionKind = "CREATE" | "UPDATE" | "DELETE" | "SYNC";

export type ApprovalState =
  | "DRAFT"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "SUPERSEDED"
  | "EXPIRED"
  | "PERMISSION_CHECK"
  | "EXECUTING"
  | "COMPLETED"
  | "DENIED"
  | "FAILED"
  | "PARTIAL";

export type ConnectionState = "connected" | "attention" | "unavailable";

export interface UserSession {
  name: string;
  initials: string;
  role: string;
  workspace: string;
}

export interface ConnectorSummary {
  system: SourceSystem;
  label: string;
  state: ConnectionState;
  detail: string;
}

export interface JiraRequest {
  id: string;
  key: string;
  title: string;
  status: JiraStatus;
  type: "Demande" | "Incident" | "Amélioration";
  priority: "Haute" | "Moyenne" | "Basse";
  updatedAt: string;
  indexation: IndexationState;
}

export interface SourceReference {
  id: string;
  system: SourceSystem;
  label: string;
  title: string;
  url?: string;
  location?: string;
  confidence?: number;
  inferred?: boolean;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  author: string;
  content: string;
  createdAt: string;
  sources?: SourceReference[];
  status?: "complete" | "streaming" | "error";
}

export interface ActionTarget {
  system: SourceSystem;
  entityType: string;
  externalId: string;
  title: string;
  destination: string;
}

export interface ActionField {
  label: string;
  value: string | string[];
}

export interface ActionDiff {
  field: string;
  before: string;
  after: string;
}

export interface ActionProposal {
  id: string;
  correlationId: string;
  kind: ActionKind;
  title: string;
  summary: string;
  target: ActionTarget;
  fields: ActionField[];
  diff: ActionDiff[];
  sources: SourceReference[];
  state: ApprovalState;
  version: number;
  payloadHash: string;
  expiresAt: string;
  decisionToken: string;
}

export type ActionDecision = "approve" | "reject" | "revise";

export interface IndexationResult {
  requestIds: string[];
  indexedAt: string;
}

export interface ActionDecisionResult {
  state: ApprovalState;
  message: string;
}

export interface ProjectAssistantSnapshot {
  session: UserSession;
  connectors: ConnectorSummary[];
  requests: JiraRequest[];
  messages: ChatMessage[];
  action: ActionProposal;
}
