import {
  AssistantGatewayError,
  type ProjectAssistantGateway,
} from "@/features/project-assistant/application/assistant-gateway";
import type {
  ActionDecision,
  ActionDecisionResult,
  ActionProposal,
  ChatMessage,
  IndexationResult,
  SourceReference,
  SourceSystem,
} from "@/features/project-assistant/domain/models";

export interface HttpAssistantGatewayOptions {
  /** Backend origin, without a trailing slash. */
  baseUrl: string;
  /** Sent as `X-Tenant-ID`. The backend derives the tenant from it, and only it. */
  tenantId: string;
  /** Sent as `X-User-ID`. */
  userId: string;
  /** Injected in tests. Defaults to the ambient `fetch`. */
  fetchImpl?: typeof fetch;
  /** Injected in tests, so the correlation id and the timestamp stay assertable. */
  newCorrelationId?: () => string;
  now?: () => Date;
}

/** The answer as `AgentAnswer` serialises it. Only the fields read here. */
interface AgentAnswerPayload {
  text: string;
  stop_reason: string;
  steps_used: number;
  sources?: AgentSourcePayload[];
}

interface AgentSourcePayload {
  source_system: string;
  tool_name: string;
  url?: string | null;
  retrieved_at: string;
  truncated?: boolean;
}

const KNOWN_SYSTEMS: readonly SourceSystem[] = ["atlassian", "jira", "confluence", "figma"];

// One message per status, because the remedy differs and a single "service
// unavailable" would tell the reader to retry when retrying cannot work. The
// backend's own `detail.message` is deliberately not shown: it is written for an
// operator, and nothing guarantees it stays free of provider wording.
const REFUSALS: Record<number, [string, string]> = {
  403: [
    "LLM_PROVIDER_DISABLED",
    "L’assistant n’est pas activé sur ce déploiement. Aucune lecture n’a été tentée.",
  ],
  413: [
    "REQUEST_TOO_LARGE",
    "La question est trop longue pour le modèle. Reformulez-la plus court : attendre ne changera rien.",
  ],
  429: [
    "RATE_LIMITED",
    "Le quota du modèle est épuisé. Réessayez dans une minute.",
  ],
  502: [
    "UPSTREAM_REFUSED",
    "La source ou le modèle a refusé la requête. Aucune réponse n’a été produite.",
  ],
  503: [
    "AUDIT_UNAVAILABLE",
    "La trace d’audit est indisponible : l’assistant refuse de lire sans pouvoir la consigner.",
  ],
  504: [
    "UPSTREAM_TIMEOUT",
    "La lecture a dépassé le temps autorisé. Aucune réponse n’a été produite.",
  ],
};

/**
 * HTTP adapter for the read path. It implements one of the three gateway methods
 * for a plain reason: `POST /api/agent/questions` is the only endpoint that
 * answers a question today. The other two refuse rather than pretend -- see the
 * comments on each.
 *
 * Read-only by construction: this adapter never calls an endpoint that mutates.
 */
export function createHttpAssistantGateway(
  options: HttpAssistantGatewayOptions,
): ProjectAssistantGateway {
  const {
    baseUrl,
    tenantId,
    userId,
    fetchImpl = globalThis.fetch,
    newCorrelationId = () => crypto.randomUUID(),
    now = () => new Date(),
  } = options;

  return {
    async indexRequests(_requestIds: string[]): Promise<IndexationResult> {
      // No backend counterpart exists: there is no index, and the reads are driven
      // by the model's own searches. Returning a fabricated success would mark the
      // requests INDEXED in the navigator and claim a state nothing produced.
      throw new AssistantGatewayError(
        "INDEXATION_UNSUPPORTED",
        "L’indexation n’existe pas côté serveur : l’assistant lit les sources à la demande.",
      );
    },

    async sendMessage(content: string): Promise<ChatMessage> {
      const correlationId = newCorrelationId();
      let response: Response;
      try {
        response = await fetchImpl(`${baseUrl}/api/agent/questions`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Tenant-ID": tenantId,
            "X-User-ID": userId,
          },
          body: JSON.stringify({ question: content, correlation_id: correlationId }),
        });
      } catch {
        throw new AssistantGatewayError(
          "TRANSPORT_FAILURE",
          "Le backend est injoignable. Aucune lecture n’a été tentée.",
        );
      }

      if (!response.ok) {
        const [code, message] = REFUSALS[response.status] ?? [
          "REFUSED",
          "La requête a été refusée par le backend. Aucune réponse n’a été produite.",
        ];
        throw new AssistantGatewayError(code, message);
      }

      const answer = (await response.json()) as AgentAnswerPayload;
      return {
        // The correlation id, not a clock: it is what ties this message to its
        // reads in the audit trail, and it is the identifier to quote in a report.
        id: correlationId,
        role: "assistant",
        author: "Nexus",
        content: answer.text,
        createdAt: formatTime(now()),
        sources: toSourceReferences(answer.sources ?? []),
        status: "complete",
      };
    },

    async decideAction(
      _proposal: ActionProposal,
      _decision: ActionDecision,
    ): Promise<ActionDecisionResult> {
      // The approvals API exists, but it decides on proposals the server created,
      // and this build produces none: mutations are off. Reporting APPROVED here
      // would show a decision that was never recorded anywhere.
      throw new AssistantGatewayError(
        "MUTATIONS_DISABLED",
        "Les actions d’écriture sont désactivées sur ce déploiement. Aucune décision n’a été enregistrée.",
      );
    },
  };
}

function toSourceReferences(sources: AgentSourcePayload[]): SourceReference[] {
  return sources.map((source, index) => ({
    // The reference when there is one, so the same source keeps the same key
    // between two answers; otherwise the position, which is stable within one.
    id: source.url ?? `${source.tool_name}-${index}`,
    system: toSourceSystem(source.source_system),
    label: labelFor(source),
    title: `Lu via ${source.tool_name} le ${formatDate(source.retrieved_at)}`,
    url: source.url ?? undefined,
    // Truncation is the one thing the reader cannot infer from the link, and the
    // answer was formed from a fragment when it is set.
    location: source.truncated ? "Extrait tronqué" : undefined,
    // `confidence` and `inferred` are left out on purpose. The backend derives its
    // citations from what was actually read, so nothing scores them and nothing is
    // inferred. Filling them with a plausible number would read as a measurement.
  }));
}

function toSourceSystem(value: string): SourceSystem {
  const known = KNOWN_SYSTEMS.find((system) => system === value);
  // A system the interface does not know is shown as Atlassian only if it says so;
  // otherwise it falls back to the broadest label rather than guessing a product.
  return known ?? "atlassian";
}

function labelFor(source: AgentSourcePayload): string {
  if (!source.url) return source.tool_name;
  const segments = source.url.split("/").filter(Boolean);
  return segments[segments.length - 1] ?? source.url;
}

function formatTime(value: Date): string {
  return new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" }).format(value);
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" }).format(parsed);
}
