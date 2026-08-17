import { describe, expect, it, vi } from "vitest";

import { createHttpAssistantGateway } from "./http-assistant-gateway";
import { AssistantGatewayError } from "@/features/project-assistant/application/assistant-gateway";

const ANSWER = {
  text: "Le ticket ABM-12 est en cours.",
  stop_reason: "answered",
  steps_used: 2,
  sources: [
    {
      source_system: "jira",
      tool_name: "getJiraIssue",
      url: "https://example.atlassian.net/browse/ABM-12",
      retrieved_at: "2026-08-17T09:30:00+00:00",
      truncated: false,
    },
  ],
};

function gatewayReturning(payload: unknown, status = 200) {
  const fetchImpl = vi.fn(async () =>
    new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  const gateway = createHttpAssistantGateway({
    baseUrl: "http://backend.test",
    tenantId: "tenant-a",
    userId: "fanny",
    fetchImpl: fetchImpl as unknown as typeof fetch,
    newCorrelationId: () => "corr-1",
    now: () => new Date("2026-08-17T09:31:00Z"),
  });
  return { fetchImpl, gateway };
}

describe("createHttpAssistantGateway", () => {
  it("posts the question with a correlation id and the identity headers", async () => {
    const { fetchImpl, gateway } = gatewayReturning(ANSWER);

    await gateway.sendMessage("Où en est ABM-12 ?");

    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend.test/api/agent/questions");
    expect(init.method).toBe("POST");
    // The backend derives the tenant from these headers alone. Sending the body
    // without them would be refused, and any weakening here is a tenant bug.
    expect(init.headers).toMatchObject({ "X-Tenant-ID": "tenant-a", "X-User-ID": "fanny" });
    expect(JSON.parse(init.body as string)).toEqual({
      question: "Où en est ABM-12 ?",
      correlation_id: "corr-1",
    });
  });

  it("carries the correlation id into the message id, so the audit trail can be found", async () => {
    const { gateway } = gatewayReturning(ANSWER);

    const message = await gateway.sendMessage("Où en est ABM-12 ?");

    expect(message.id).toBe("corr-1");
    expect(message.content).toBe("Le ticket ABM-12 est en cours.");
    expect(message.status).toBe("complete");
  });

  it("keeps the backend link and never scores a source", async () => {
    const { gateway } = gatewayReturning(ANSWER);

    const [source] = (await gateway.sendMessage("q")).sources ?? [];

    expect(source.url).toBe("https://example.atlassian.net/browse/ABM-12");
    expect(source.label).toBe("ABM-12");
    // Nothing in the backend's provenance measures a confidence or infers a
    // source. A plausible number here would read as a measurement.
    expect(source.confidence).toBeUndefined();
    expect(source.inferred).toBeUndefined();
  });

  it("shows a truncated read as truncated", async () => {
    const { gateway } = gatewayReturning({
      ...ANSWER,
      sources: [{ ...ANSWER.sources[0], truncated: true }],
    });

    const [source] = (await gateway.sendMessage("q")).sources ?? [];

    expect(source.location).toBe("Extrait tronqué");
  });

  it("labels a collection read by its tool, having no resource to name", async () => {
    const { gateway } = gatewayReturning({
      ...ANSWER,
      sources: [
        {
          source_system: "atlassian",
          tool_name: "searchJiraIssuesUsingJql",
          url: null,
          retrieved_at: "2026-08-17T09:30:00+00:00",
        },
      ],
    });

    const [source] = (await gateway.sendMessage("q")).sources ?? [];

    expect(source.url).toBeUndefined();
    expect(source.label).toBe("searchJiraIssuesUsingJql");
    expect(source.system).toBe("atlassian");
  });

  it("falls back to the broad label rather than guessing a product", async () => {
    const { gateway } = gatewayReturning({
      ...ANSWER,
      sources: [{ ...ANSWER.sources[0], source_system: "bitbucket" }],
    });

    const [source] = (await gateway.sendMessage("q")).sources ?? [];

    expect(source.system).toBe("atlassian");
  });

  it.each([
    [403, "LLM_PROVIDER_DISABLED"],
    [413, "REQUEST_TOO_LARGE"],
    [429, "RATE_LIMITED"],
    [502, "UPSTREAM_REFUSED"],
    [503, "AUDIT_UNAVAILABLE"],
    [504, "UPSTREAM_TIMEOUT"],
  ])("translates %i into a refusal the reader can act on", async (status, code) => {
    const { gateway } = gatewayReturning(
      { detail: { code: "INTERNAL", message: "groq said no" } },
      status,
    );

    const error = await gateway.sendMessage("q").catch((cause) => cause);

    expect(error).toBeInstanceOf(AssistantGatewayError);
    expect((error as AssistantGatewayError).code).toBe(code);
    // The backend's own message is written for an operator and may quote the
    // provider. It must not reach the conversation.
    expect((error as AssistantGatewayError).message).not.toContain("groq");
  });

  it("reports an unreachable backend without claiming a read was attempted", async () => {
    const gateway = createHttpAssistantGateway({
      baseUrl: "http://backend.test",
      tenantId: "tenant-a",
      userId: "fanny",
      fetchImpl: (async () => {
        throw new TypeError("Failed to fetch");
      }) as unknown as typeof fetch,
    });

    const error = await gateway.sendMessage("q").catch((cause) => cause);

    expect((error as AssistantGatewayError).code).toBe("TRANSPORT_FAILURE");
  });

  it("refuses indexation instead of reporting a state nothing produced", async () => {
    const { fetchImpl, gateway } = gatewayReturning(ANSWER);

    const error = await gateway.indexRequests(["req-1"]).catch((cause) => cause);

    expect((error as AssistantGatewayError).code).toBe("INDEXATION_UNSUPPORTED");
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("refuses a decision while mutations are disabled, and calls nothing", async () => {
    const { fetchImpl, gateway } = gatewayReturning(ANSWER);

    const error = await gateway
      .decideAction({ id: "proposal-1" } as never, "approve")
      .catch((cause) => cause);

    expect((error as AssistantGatewayError).code).toBe("MUTATIONS_DISABLED");
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
