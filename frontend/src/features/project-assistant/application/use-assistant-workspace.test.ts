import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ProjectAssistantGateway } from "./assistant-gateway";
import { useAssistantWorkspace } from "./use-assistant-workspace";
import type { ProjectAssistantSnapshot } from "../domain/models";
import {
  demoActionProposal,
  demoConnectors,
  demoMessages,
  demoRequests,
  demoSession,
} from "../demo/fixtures";

function buildSnapshot(): ProjectAssistantSnapshot {
  return {
    action: { ...demoActionProposal },
    connectors: demoConnectors.map((connector) => ({ ...connector })),
    messages: demoMessages.map((message) => ({ ...message })),
    requests: demoRequests.map((request) => ({ ...request })),
    session: { ...demoSession },
  };
}

function buildGateway(): ProjectAssistantGateway {
  return {
    decideAction: vi.fn<ProjectAssistantGateway["decideAction"]>(
      async (_proposal, decision) => ({
        message: `Decision: ${decision}`,
        state: decision === "approve" ? "PERMISSION_CHECK" : "REJECTED",
      }),
    ),
    indexRequests: vi.fn<ProjectAssistantGateway["indexRequests"]>(async (requestIds) => ({
      indexedAt: "2026-08-04T00:00:00.000Z",
      requestIds,
    })),
    sendMessage: vi.fn<ProjectAssistantGateway["sendMessage"]>(async (content) => ({
      author: "Nexus",
      content: `Response: ${content}`,
      createdAt: "12:00",
      id: "assistant-test",
      role: "assistant",
      status: "complete",
    })),
  };
}

describe("useAssistantWorkspace", () => {
  it("indexes only selected requests that are not already indexed", async () => {
    const snapshot = buildSnapshot();
    const gateway = buildGateway();
    const candidate = snapshot.requests.find(({ indexation }) => indexation !== "INDEXED");
    expect(candidate).toBeDefined();

    const { result } = renderHook(() => useAssistantWorkspace(snapshot, gateway));
    act(() => result.current.toggleRequest(candidate!.id));
    await act(() => result.current.indexSelectedRequests());

    expect(gateway.indexRequests).toHaveBeenCalledWith([candidate!.id]);
    expect(result.current.requests.find(({ id }) => id === candidate!.id)?.indexation).toBe(
      "INDEXED",
    );
    expect(result.current.isIndexing).toBe(false);
  });

  it("adds the user message and the assistant response", async () => {
    const snapshot = buildSnapshot();
    const gateway = buildGateway();
    const { result } = renderHook(() => useAssistantWorkspace(snapshot, gateway));

    await act(() => result.current.sendMessage("Quels tickets sont similaires ?"));

    expect(gateway.sendMessage).toHaveBeenCalledWith("Quels tickets sont similaires ?");
    expect(result.current.messages.at(-2)?.role).toBe("user");
    expect(result.current.messages.at(-1)?.content).toBe(
      "Response: Quels tickets sont similaires ?",
    );
  });

  it("updates the proposal only after the gateway confirms a decision", async () => {
    const snapshot = buildSnapshot();
    const gateway = buildGateway();
    const { result } = renderHook(() => useAssistantWorkspace(snapshot, gateway));

    await act(() => result.current.decideAction("approve"));

    expect(gateway.decideAction).toHaveBeenCalledWith(snapshot.action, "approve");
    expect(result.current.action.state).toBe("PERMISSION_CHECK");
    expect(result.current.decisionFeedback).toBe("Decision: approve");
    expect(result.current.busyDecision).toBeNull();
  });

  it("fails closed when a decision cannot be recorded", async () => {
    const snapshot = buildSnapshot();
    const gateway = buildGateway();
    vi.mocked(gateway.decideAction).mockRejectedValueOnce(new Error("network"));
    const { result } = renderHook(() => useAssistantWorkspace(snapshot, gateway));

    await act(() => result.current.decideAction("approve"));

    expect(result.current.action.state).toBe(snapshot.action.state);
    expect(result.current.error).toContain("reste non exécutée");
  });
});
