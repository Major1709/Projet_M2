"use client";

import { useState } from "react";

import { AssistantGatewayError, type ProjectAssistantGateway } from "./assistant-gateway";
import type {
  ActionDecision,
  ActionProposal,
  ChatMessage,
  ProjectAssistantSnapshot,
} from "../domain/models";

export interface AssistantWorkspaceState {
  action: ActionProposal;
  busyDecision: ActionDecision | null;
  decisionFeedback: string | null;
  error: string | null;
  isIndexing: boolean;
  isResponding: boolean;
  messages: ChatMessage[];
  requests: ProjectAssistantSnapshot["requests"];
  selectedIds: Set<string>;
}

export interface AssistantWorkspaceActions {
  decideAction(decision: ActionDecision): Promise<void>;
  indexSelectedRequests(): Promise<void>;
  resetAction(): void;
  sendMessage(content: string): Promise<void>;
  toggleRequest(requestId: string): void;
}

/**
 * Deep application module for the assistant screen. UI modules consume its
 * state and five user actions without knowing about transport or state rules.
 */
export function useAssistantWorkspace(
  initial: ProjectAssistantSnapshot,
  gateway: ProjectAssistantGateway,
): AssistantWorkspaceState & AssistantWorkspaceActions {
  const [requests, setRequests] = useState(initial.requests);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    new Set(initial.requests.filter(({ indexation }) => indexation === "INDEXED").map(({ id }) => id)),
  );
  const [messages, setMessages] = useState(initial.messages);
  const [action, setAction] = useState(initial.action);
  const [isIndexing, setIsIndexing] = useState(false);
  const [isResponding, setIsResponding] = useState(false);
  const [busyDecision, setBusyDecision] = useState<ActionDecision | null>(null);
  const [decisionFeedback, setDecisionFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function toggleRequest(requestId: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(requestId)) next.delete(requestId);
      else next.add(requestId);
      return next;
    });
  }

  async function indexSelectedRequests() {
    const requestIds = requests
      .filter(({ id, indexation }) => selectedIds.has(id) && indexation !== "INDEXED")
      .map(({ id }) => id);

    if (!requestIds.length) return;
    setError(null);
    setIsIndexing(true);
    setRequests((current) =>
      current.map((request) =>
        requestIds.includes(request.id) ? { ...request, indexation: "INDEXING" } : request,
      ),
    );

    try {
      const result = await gateway.indexRequests(requestIds);
      setRequests((current) =>
        current.map((request) =>
          result.requestIds.includes(request.id) ? { ...request, indexation: "INDEXED" } : request,
        ),
      );
    } catch (cause) {
      setRequests((current) =>
        current.map((request) =>
          requestIds.includes(request.id) ? { ...request, indexation: "FAILED" } : request,
        ),
      );
      setError(
        reasonFor(cause, "L’indexation a échoué. Réessayez après avoir vérifié la connexion Jira."),
      );
    } finally {
      setIsIndexing(false);
    }
  }

  async function sendMessage(content: string) {
    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      author: "Vous",
      content,
      createdAt: formatTime(new Date()),
      status: "complete",
    };

    setError(null);
    setMessages((current) => [...current, userMessage]);
    setIsResponding(true);
    try {
      const response = await gateway.sendMessage(content);
      setMessages((current) => [...current, response]);
    } catch (cause) {
      const reason = reasonFor(
        cause,
        "La réponse n’a pas pu être générée. Aucune action externe n’a été exécutée.",
      );
      setMessages((current) => [
        ...current,
        {
          id: `assistant-error-${Date.now()}`,
          role: "assistant",
          author: "NEXIA",
          content: reason,
          createdAt: formatTime(new Date()),
          status: "error",
        },
      ]);
      setError(reason);
    } finally {
      setIsResponding(false);
    }
  }

  async function decideAction(decision: ActionDecision) {
    setBusyDecision(decision);
    setDecisionFeedback(null);
    setError(null);
    try {
      const result = await gateway.decideAction(action, decision);
      setAction((current) => ({ ...current, state: result.state }));
      setDecisionFeedback(result.message);
    } catch (cause) {
      setError(
        reasonFor(cause, "La décision n’a pas été enregistrée. L’action reste non exécutée."),
      );
    } finally {
      setBusyDecision(null);
    }
  }

  function resetAction() {
    setAction(initial.action);
    setDecisionFeedback(null);
    setBusyDecision(null);
    setError(null);
  }

  return {
    action,
    busyDecision,
    decisionFeedback,
    error,
    isIndexing,
    isResponding,
    messages,
    requests,
    selectedIds,
    decideAction,
    indexSelectedRequests,
    resetAction,
    sendMessage,
    toggleRequest,
  };
}

/**
 * A refusal the gateway phrased, or the screen's own wording.
 *
 * The distinction matters: an `AssistantGatewayError` says what happened and what
 * to do about it -- quota exhausted, mutations off -- whereas an arbitrary
 * exception carries a message written for a developer, and showing it would leak
 * transport detail into the conversation.
 */
function reasonFor(cause: unknown, fallback: string) {
  return cause instanceof AssistantGatewayError ? cause.message : fallback;
}

function formatTime(value: Date) {
  return new Intl.DateTimeFormat("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(value);
}
