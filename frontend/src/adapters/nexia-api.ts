const DEFAULT_API_BASE_URL = "http://localhost:8000";

export type NexiaSource = {
  title: string;
  url?: string;
  provider?: string;
  retrievedAt?: string;
  truncated?: boolean;
};

export type NexiaApprovalTarget = "jira" | "confluence" | "figma";

export type NexiaMutationActionClass = "CREATE" | "UPDATE" | "DELETE";

export type NexiaMutationProposalState =
  | "DRAFT"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "SUPERSEDED"
  | "EXPIRED"
  | "PERMISSION_CHECK"
  | "DENIED"
  | "EXECUTING"
  | "COMPLETED"
  | "FAILED"
  | "PARTIAL";

export type NexiaMutationPayload = {
  projectKey?: string;
  issueTypeName?: string;
  summary?: string;
  description?: string;
};

export type NexiaActionTarget = {
  source_system: NexiaApprovalTarget;
  resource_type: string;
  resource_id?: string | null;
  title?: string | null;
  container_id?: string | null;
  resource_version?: string | null;
};

/**
 * The assistant may return a server-created write proposal alongside its text.
 * The fields are deliberately display-only: approval and execution remain
 * server-side actions and are not inferred by the browser.
 */
export type NexiaApproval = {
  target: NexiaApprovalTarget;
  proposalId?: string;
  decisionToken?: string;
  version?: number;
  state?: NexiaMutationProposalState;
  actionClass?: NexiaMutationActionClass;
  toolName?: string;
  payload?: NexiaMutationPayload;
  explanation?: string;
  expiresAt?: string;
  action?: string;
  destination?: string;
  icon?: string;
  iconAlt?: string;
  objectType?: string;
  project?: string;
  title?: string;
  description?: string;
  label?: string;
  expiresInMinutes?: number;
};

export type NexiaAnswer = {
  answer: string;
  sources: NexiaSource[];
  approval?: NexiaApproval;
};

type ConversationResponse = {
  id?: unknown;
};

type QuestionResponse = {
  text?: unknown;
  sources?: unknown;
  approval?: unknown;
};

export type NexiaGateway = {
  createConversation: (signal?: AbortSignal) => Promise<string>;
  askQuestion: (input: {
    question: string;
    correlationId: string;
    conversationId: string;
    signal?: AbortSignal;
  }) => Promise<NexiaAnswer>;
  createActionProposal: (input: {
    conversationId: string;
    sourceSystem: NexiaApprovalTarget;
    toolName: string;
    actionClass: NexiaMutationActionClass;
    target: NexiaActionTarget;
    payload: NexiaMutationPayload;
    explanation?: string;
    correlationId: string;
  }) => Promise<NexiaApproval>;
  approveActionProposal: (input: {
    proposalId: string;
    expectedVersion: number;
    decisionToken: string;
    reason?: string;
  }) => Promise<NexiaApproval>;
  rejectActionProposal: (input: {
    proposalId: string;
    expectedVersion: number;
    decisionToken: string;
    reason?: string;
  }) => Promise<NexiaApproval>;
  executeActionProposal: (input: {
    proposalId: string;
    expectedVersion: number;
  }) => Promise<NexiaMutationExecution>;
  signOut: () => Promise<void>;
};

export type NexiaMutationExecution = {
  succeeded: boolean;
  partial: boolean;
  externalIds: string[];
  errorCode?: string;
  safeMessage?: string;
};

export class NexiaApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "NexiaApiError";
  }
}

function getApiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL).replace(/\/$/, "");
}

async function parseJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new NexiaApiError("La réponse reçue est invalide.", response.status);
  }
}

async function parseErrorCode(response: Response): Promise<string | undefined> {
  try {
    const payload = await response.json() as Record<string, unknown>;
    const detail = payload.detail && typeof payload.detail === "object"
      ? payload.detail as Record<string, unknown>
      : {};
    return typeof detail.code === "string" ? detail.code : undefined;
  } catch {
    return undefined;
  }
}

function getSafeSourceUrl(value: unknown): string | undefined {
  if (typeof value !== "string" || !value.trim()) {
    return undefined;
  }

  try {
    const parsed = new URL(value.trim());
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return undefined;
    }
    return parsed.toString();
  } catch {
    return undefined;
  }
}

async function request(path: string, init: RequestInit): Promise<Response> {
  let response: Response;

  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new NexiaApiError("Le service NEXIA est temporairement inaccessible.", 0);
  }

  if (!response.ok) {
    const code = await parseErrorCode(response);
    const messageByCode: Record<string, string> = {
      IDENTITY_REQUIRED: "Votre session a expiré. Veuillez vous reconnecter.",
      SESSION_REQUIRED: "Une session authentifiée est requise pour cette écriture.",
      MCP_MUTATIONS_DISABLED: "Les écritures externes sont désactivées dans cet environnement.",
      PROPOSAL_NOT_FOUND: "Cette proposition n’existe plus ou n’est plus accessible.",
      VERSION_CONFLICT: "La proposition a changé. Rechargez-la avant de décider.",
      INVALID_TRANSITION: "L’état de la proposition a changé. Rechargez-la avant de décider.",
      INVALID_DECISION_TOKEN: "Cette décision n’est plus valide. La proposition doit être recréée.",
      PROPOSAL_EXPIRED: "La fenêtre d’approbation est expirée. Demandez une nouvelle proposition.",
      MUTATION_OUTCOME_UNKNOWN: "L’écriture a été envoyée, mais sa confirmation est inconnue. Vérifiez dans Jira avant toute nouvelle tentative.",
    };
    const messageByStatus: Partial<Record<number, string>> = {
      401: "Votre session a expiré. Veuillez vous reconnecter.",
      403: "Vous n’avez pas l’autorisation d’effectuer cette action.",
      413: "Ce message est trop long pour être envoyé.",
      422: "Le message n’a pas pu être validé.",
      429: "Trop de demandes ont été envoyées. Patientez un instant.",
      502: "Le service NEXIA est temporairement indisponible.",
      503: "Le service NEXIA est temporairement indisponible.",
      504: "Le service NEXIA met trop de temps à répondre.",
    };
    throw new NexiaApiError(
      (code ? messageByCode[code] : undefined)
        ?? messageByStatus[response.status]
        ?? "La demande n’a pas pu être traitée. Réessayez dans un instant.",
      response.status,
      code,
    );
  }

  return response;
}

function parseSources(value: unknown): NexiaSource[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.flatMap((source) => {
    if (!source || typeof source !== "object") {
      return [];
    }

    const candidate = source as Record<string, unknown>;
    const title = candidate.tool_name;
    if (typeof title !== "string" || !title.trim()) {
      return [];
    }

    const safeUrl = getSafeSourceUrl(candidate.url);

    return [{
      title: title.trim(),
      ...(safeUrl ? { url: safeUrl } : {}),
      ...(typeof candidate.source_system === "string"
        ? { provider: candidate.source_system.trim() }
        : {}),
      ...(typeof candidate.retrieved_at === "string"
        ? { retrievedAt: candidate.retrieved_at }
        : {}),
      ...(typeof candidate.truncated === "boolean"
        ? { truncated: candidate.truncated }
        : {}),
    }];
  });
}

function firstString(...values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

function approvalTarget(value: unknown): NexiaApprovalTarget | undefined {
  const normalized = typeof value === "string" ? value.trim().toLowerCase() : "";
  if (normalized.includes("jira")) return "jira";
  if (normalized.includes("confluence")) return "confluence";
  if (normalized.includes("figma")) return "figma";
  return undefined;
}

function parseApproval(value: unknown): NexiaApproval | undefined {
  if (!value || typeof value !== "object") return undefined;

  const candidate = value as Record<string, unknown>;
  const targetRecord = candidate.target && typeof candidate.target === "object"
    ? candidate.target as Record<string, unknown>
    : {};
  const payload = candidate.payload && typeof candidate.payload === "object"
    ? candidate.payload as Record<string, unknown>
    : {};
  const target = approvalTarget(
    candidate.targetSystem
      ?? candidate.source_system
      ?? candidate.sourceSystem
      ?? targetRecord.source_system
      ?? targetRecord.sourceSystem,
  );

  if (!target) return undefined;

  const actionClass = firstString(candidate.action_class, candidate.actionClass)?.toUpperCase();
  const actionObject = target === "jira" ? "un ticket"
    : target === "confluence" ? "une page" : "un processus";
  const action = firstString(candidate.action)
    ?? (actionClass === "UPDATE" ? `Modifier ${actionObject}`
      : actionClass === "DELETE" ? `Supprimer ${actionObject}`
        : `Créer ${actionObject}`);
  const project = firstString(
    candidate.project,
    candidate.space,
    payload.projectKey,
    payload.projectId,
    payload.spaceKey,
    payload.spaceId,
    targetRecord.container_id,
    targetRecord.containerId,
  );
  const title = firstString(
    candidate.title,
    payload.title,
    payload.summary,
    targetRecord.title,
  );
  const description = firstString(candidate.description, payload.description);
  const sourceLabel = target[0].toUpperCase() + target.slice(1);
  const targetLabel = firstString(candidate.destination)
    ?? (project ? `${sourceLabel} · ${project}` : sourceLabel);
  const proposalState = firstString(candidate.state)?.toUpperCase();
  const validStates = new Set<NexiaMutationProposalState>([
    "DRAFT",
    "PENDING_APPROVAL",
    "APPROVED",
    "REJECTED",
    "SUPERSEDED",
    "EXPIRED",
    "PERMISSION_CHECK",
    "DENIED",
    "EXECUTING",
    "COMPLETED",
    "FAILED",
    "PARTIAL",
  ]);
  const normalizedActionClass = actionClass === "CREATE" || actionClass === "UPDATE" || actionClass === "DELETE"
    ? actionClass
    : undefined;
  const normalizedState = proposalState && validStates.has(proposalState as NexiaMutationProposalState)
    ? proposalState as NexiaMutationProposalState
    : undefined;
  const mutationPayload: NexiaMutationPayload = {
    ...(typeof payload.projectKey === "string" ? { projectKey: payload.projectKey } : {}),
    ...(typeof payload.issueTypeName === "string" ? { issueTypeName: payload.issueTypeName } : {}),
    ...(typeof payload.summary === "string" ? { summary: payload.summary } : {}),
    ...(typeof payload.description === "string" ? { description: payload.description } : {}),
  };

  return {
    target,
    ...(firstString(candidate.id) ? { proposalId: firstString(candidate.id) } : {}),
    ...(firstString(candidate.decision_token, candidate.decisionToken)
      ? { decisionToken: firstString(candidate.decision_token, candidate.decisionToken) }
      : {}),
    ...(typeof candidate.version === "number" ? { version: candidate.version } : {}),
    ...(normalizedState ? { state: normalizedState } : {}),
    ...(normalizedActionClass ? { actionClass: normalizedActionClass } : {}),
    ...(firstString(candidate.tool_name, candidate.toolName)
      ? { toolName: firstString(candidate.tool_name, candidate.toolName) }
      : {}),
    ...(Object.keys(mutationPayload).length > 0 ? { payload: mutationPayload } : {}),
    ...(firstString(candidate.explanation) ? { explanation: firstString(candidate.explanation) } : {}),
    ...(firstString(candidate.expires_at, candidate.expiresAt)
      ? { expiresAt: firstString(candidate.expires_at, candidate.expiresAt) }
      : {}),
    action,
    ...(targetLabel ? { destination: targetLabel } : {}),
    ...(firstString(candidate.objectType, targetRecord.resource_type)
      ? { objectType: firstString(candidate.objectType, targetRecord.resource_type) }
      : {}),
    ...(project ? { project } : {}),
    ...(title ? { title } : {}),
    ...(description ? { description } : {}),
    ...(firstString(candidate.label) ? { label: firstString(candidate.label) } : {}),
    ...(typeof candidate.expiresInMinutes === "number"
      ? { expiresInMinutes: candidate.expiresInMinutes }
      : {}),
  };
}

function parseMutationExecution(value: unknown, status: number): NexiaMutationExecution {
  if (!value || typeof value !== "object") {
    throw new NexiaApiError("La réponse d’exécution reçue est invalide.", status);
  }

  const candidate = value as Record<string, unknown>;
  if (typeof candidate.succeeded !== "boolean" || typeof candidate.partial !== "boolean") {
    throw new NexiaApiError("La réponse d’exécution reçue est invalide.", status);
  }

  return {
    succeeded: candidate.succeeded,
    partial: candidate.partial,
    externalIds: Array.isArray(candidate.external_ids)
      ? candidate.external_ids.filter((id): id is string => typeof id === "string")
      : [],
    ...(typeof candidate.error_code === "string" ? { errorCode: candidate.error_code } : {}),
    ...(typeof candidate.safe_message === "string" ? { safeMessage: candidate.safe_message } : {}),
  };
}

function requireApproval(value: unknown, status: number): NexiaApproval {
  const approval = parseApproval(value);
  if (!approval?.proposalId || approval.version === undefined || !approval.state) {
    throw new NexiaApiError("La proposition d’écriture reçue est invalide.", status);
  }
  return approval;
}

function requireCreatedApproval(value: unknown, status: number): NexiaApproval {
  const approval = requireApproval(value, status);
  if (!approval.decisionToken) {
    throw new NexiaApiError("Le jeton de décision de la proposition est absent.", status);
  }
  return approval;
}

export async function createConversation(signal?: AbortSignal): Promise<string> {
  const response = await request("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ title: null }),
    signal,
  });
  const payload = (await parseJson(response)) as ConversationResponse;

  if (typeof payload.id !== "string" || !payload.id) {
    throw new NexiaApiError("La conversation créée est invalide.", response.status);
  }

  return payload.id;
}

export async function askQuestion(input: {
  question: string;
  correlationId: string;
  conversationId: string;
  signal?: AbortSignal;
}): Promise<NexiaAnswer> {
  const response = await request("/api/agent/questions", {
    method: "POST",
    body: JSON.stringify({
      question: input.question,
      correlation_id: input.correlationId,
      conversation_id: input.conversationId,
    }),
    signal: input.signal,
  });
  const payload = (await parseJson(response)) as QuestionResponse;
  const answer = typeof payload.text === "string" && payload.text.trim()
    ? payload.text
    : null;

  if (!answer) {
    throw new NexiaApiError("La réponse reçue est invalide.", response.status);
  }

  const approval = parseApproval(payload.approval);
  return {
    answer,
    sources: parseSources(payload.sources),
    ...(approval ? { approval } : {}),
  };
}

export async function createActionProposal(input: {
  conversationId: string;
  sourceSystem: NexiaApprovalTarget;
  toolName: string;
  actionClass: NexiaMutationActionClass;
  target: NexiaActionTarget;
  payload: NexiaMutationPayload;
  explanation?: string;
  correlationId: string;
}): Promise<NexiaApproval> {
  const response = await request("/api/actions", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: input.conversationId,
      source_system: input.sourceSystem,
      tool_name: input.toolName,
      action_class: input.actionClass,
      target: input.target,
      payload: input.payload,
      ...(input.explanation ? { explanation: input.explanation } : {}),
      correlation_id: input.correlationId,
    }),
  });
  return requireCreatedApproval(await parseJson(response), response.status);
}

async function decideActionProposal(
  proposalId: string,
  path: "approve" | "reject",
  input: { expectedVersion: number; decisionToken: string; reason?: string },
): Promise<NexiaApproval> {
  const response = await request(`/api/actions/${encodeURIComponent(proposalId)}/${path}`, {
    method: "POST",
    body: JSON.stringify({
      expected_version: input.expectedVersion,
      decision_token: input.decisionToken,
      ...(input.reason ? { reason: input.reason } : {}),
    }),
  });
  return requireApproval(await parseJson(response), response.status);
}

export async function approveActionProposal(input: {
  proposalId: string;
  expectedVersion: number;
  decisionToken: string;
  reason?: string;
}): Promise<NexiaApproval> {
  return decideActionProposal(input.proposalId, "approve", input);
}

export async function rejectActionProposal(input: {
  proposalId: string;
  expectedVersion: number;
  decisionToken: string;
  reason?: string;
}): Promise<NexiaApproval> {
  return decideActionProposal(input.proposalId, "reject", input);
}

export async function executeActionProposal(input: {
  proposalId: string;
  expectedVersion: number;
}): Promise<NexiaMutationExecution> {
  const response = await request(`/api/actions/${encodeURIComponent(input.proposalId)}/execute`, {
    method: "POST",
    body: JSON.stringify({ expected_version: input.expectedVersion }),
  });
  return parseMutationExecution(await parseJson(response), response.status);
}

export async function signOut(): Promise<void> {
  await request("/api/auth/atlassian/signout", { method: "POST" });
}

export const nexiaApi: NexiaGateway = {
  createConversation,
  askQuestion,
  createActionProposal,
  approveActionProposal,
  rejectActionProposal,
  executeActionProposal,
  signOut,
};
