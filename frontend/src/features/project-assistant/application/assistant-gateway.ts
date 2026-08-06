import type {
  ActionDecision,
  ActionDecisionResult,
  ActionProposal,
  ChatMessage,
  IndexationResult,
} from "../domain/models";

/**
 * Remote-owned seam used by the feature. The demo adapter and the future
 * HTTP/SSE adapter both satisfy this small interface.
 */
export interface ProjectAssistantGateway {
  indexRequests(requestIds: string[]): Promise<IndexationResult>;
  sendMessage(content: string): Promise<ChatMessage>;
  decideAction(
    proposal: ActionProposal,
    decision: ActionDecision,
  ): Promise<ActionDecisionResult>;
}
