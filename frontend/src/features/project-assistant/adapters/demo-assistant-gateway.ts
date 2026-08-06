import type { ProjectAssistantGateway } from "@/features/project-assistant/application/assistant-gateway";
import type {
  ActionDecision,
  ActionDecisionResult,
  ActionProposal,
  ChatMessage,
  IndexationResult,
} from "@/features/project-assistant/domain/models";

const wait = (duration: number) =>
  new Promise<void>((resolve) => window.setTimeout(resolve, duration));

/**
 * Local interaction adapter. It never performs a network request or calls an MCP.
 * Replace this implementation with an HTTP/SSE adapter when backend contracts exist.
 */
export const demoAssistantGateway: ProjectAssistantGateway = {
  async indexRequests(requestIds: string[]): Promise<IndexationResult> {
    await wait(700);
    return { requestIds, indexedAt: new Date().toISOString() };
  },

  async sendMessage(content: string): Promise<ChatMessage> {
    await wait(550);
    return {
      id: `demo-assistant-${Date.now()}`,
      role: "assistant",
      author: "Nexus",
      content: `Mode démonstration : j’ai bien reçu « ${content} ». La réponse réelle sera diffusée par le backend avec ses sources autorisées et son identifiant de corrélation.`,
      createdAt: new Intl.DateTimeFormat("fr-FR", {
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date()),
      status: "complete",
    };
  },

  async decideAction(
    _proposal: ActionProposal,
    decision: ActionDecision,
  ): Promise<ActionDecisionResult> {
    await wait(450);

    const results: Record<ActionDecision, ActionDecisionResult> = {
      approve: {
        state: "PERMISSION_CHECK",
        message:
          "Approbation enregistrée. En production, le backend recontrôlera les permissions avant l’exécution MCP.",
      },
      reject: {
        state: "REJECTED",
        message: "Proposition rejetée. Aucun appel MCP n’a été exécuté.",
      },
      revise: {
        state: "SUPERSEDED",
        message:
          "Modification demandée. Une nouvelle version du payload devra être présentée et approuvée.",
      },
    };

    return results[decision];
  },
};
