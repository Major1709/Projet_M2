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
/**
 * A refusal already phrased for the reader. Part of the port, not of one adapter:
 * the application module decides that such a message is shown as it is, and any
 * adapter may raise one. Anything else thrown stays generic, because an arbitrary
 * error's text is not written for this screen.
 */
export class AssistantGatewayError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "AssistantGatewayError";
    this.code = code;
  }
}

export interface ProjectAssistantGateway {
  indexRequests(requestIds: string[]): Promise<IndexationResult>;
  sendMessage(content: string): Promise<ChatMessage>;
  decideAction(
    proposal: ActionProposal,
    decision: ActionDecision,
  ): Promise<ActionDecisionResult>;
}
