import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  NexiaApiError,
  askQuestion,
  approveActionProposal,
  createConversation,
  createActionProposal,
  executeActionProposal,
  rejectActionProposal,
  signOut,
} from "./nexia-api";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.nexia.test/";
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
});

describe("createConversation", () => {
  it("crée un fil avec les cookies de session et sans en-tête d’identité", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "conversation-123" }, 201));

    await expect(createConversation()).resolves.toBe("conversation-123");

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.nexia.test/api/conversations");
    expect(init).toMatchObject({
      method: "POST",
      credentials: "include",
      body: JSON.stringify({ title: null }),
    });
    expect(init?.headers).toEqual({
      Accept: "application/json",
      "Content-Type": "application/json",
    });

    const headerNames = Object.keys(init?.headers as Record<string, string>).map((name) => (
      name.toLowerCase()
    ));
    expect(headerNames).not.toContain("x-user-id");
    expect(headerNames).not.toContain("x-user-email");
    expect(headerNames).not.toContain("authorization");
  });

  it("refuse un identifiant de conversation manquant", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: null }, 201));

    await expect(createConversation()).rejects.toMatchObject({
      name: "NexiaApiError",
      message: "La conversation créée est invalide.",
      status: 201,
    });
  });
});

describe("askQuestion", () => {
  it("envoie le contrat backend et normalise les sources sûres", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      text: "Voici la réponse.",
      sources: [
        {
          source_system: "confluence",
          tool_name: " Page Confluence ",
          url: "https://example.test/wiki/page?q=nexia",
          retrieved_at: "2026-08-31T10:00:00Z",
          truncated: true,
        },
        {
          source_system: "jira",
          tool_name: "Ticket Jira",
          url: "javascript:alert(1)",
          truncated: false,
        },
        { source_system: "figma", url: "https://example.test/design" },
      ],
    }));

    await expect(askQuestion({
      question: "Quel est le statut ?",
      correlationId: "correlation-123",
      conversationId: "conversation-123",
    })).resolves.toEqual({
      answer: "Voici la réponse.",
      sources: [
        {
          title: "Page Confluence",
          provider: "confluence",
          url: "https://example.test/wiki/page?q=nexia",
          retrievedAt: "2026-08-31T10:00:00Z",
          truncated: true,
        },
        {
          title: "Ticket Jira",
          provider: "jira",
          truncated: false,
        },
      ],
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(init).toMatchObject({
      method: "POST",
      credentials: "include",
      body: JSON.stringify({
        question: "Quel est le statut ?",
        correlation_id: "correlation-123",
        conversation_id: "conversation-123",
      }),
    });
  });

  it("refuse une réponse textuelle vide", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ text: "   ", sources: [] }));

    await expect(askQuestion({
      question: "Question",
      correlationId: "correlation-123",
      conversationId: "conversation-123",
    })).rejects.toMatchObject({
      message: "La réponse reçue est invalide.",
      status: 200,
    });
  });

  it("projette une proposition d’écriture pour l’aperçu inline du chat", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      text: "J’ai préparé le ticket, vérifiez la proposition.",
      sources: [],
      approval: {
        source_system: "jira",
        action_class: "CREATE",
        target: {
          source_system: "jira",
          resource_type: "User Story",
          container_id: "PKA",
        },
        payload: {
          projectKey: "PKA",
          summary: "Stabiliser le viewport du chat",
          description: "Conserver la zone de saisie visible.",
        },
        expiresInMinutes: 14,
      },
    }));

    await expect(askQuestion({
      question: "Prépare un ticket Jira",
      correlationId: "correlation-123",
      conversationId: "conversation-123",
    })).resolves.toEqual({
      answer: "J’ai préparé le ticket, vérifiez la proposition.",
      sources: [],
      approval: {
        target: "jira",
        action: "Créer un ticket",
        actionClass: "CREATE",
        destination: "Jira · PKA",
        objectType: "User Story",
        project: "PKA",
        title: "Stabiliser le viewport du chat",
        description: "Conserver la zone de saisie visible.",
        payload: {
          projectKey: "PKA",
          summary: "Stabiliser le viewport du chat",
          description: "Conserver la zone de saisie visible.",
        },
        expiresInMinutes: 14,
      },
    });
  });
});

describe("signOut", () => {
  it("déconnecte la session avec les cookies sans corps JSON", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(signOut()).resolves.toBeUndefined();

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("https://api.nexia.test/api/auth/atlassian/signout");
    expect(init).toMatchObject({ method: "POST", credentials: "include" });
    expect(init?.body).toBeUndefined();
    expect(init?.headers).toEqual({ Accept: "application/json" });
  });
});

describe("actions d’écriture", () => {
  const proposalResponse = {
    id: "proposal-123",
    decision_token: "decision-token-123456789012345",
    version: 1,
    state: "PENDING_APPROVAL",
    source_system: "jira",
    action_class: "CREATE",
    tool_name: "createJiraIssue",
    target: { source_system: "jira", resource_type: "User Story", container_id: "PKA" },
    payload: {
      projectKey: "PKA",
      issueTypeName: "User Story",
      summary: "Stabiliser le viewport du chat",
      description: "Conserver la zone de saisie visible.",
      ignored: "ne doit pas être affiché",
    },
    explanation: "La demande explicite de l’utilisateur correspond à cette création.",
  };

  it("crée une proposition et conserve le decision_token côté client", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(proposalResponse, 201));

    await expect(createActionProposal({
      conversationId: "conversation-123",
      sourceSystem: "jira",
      toolName: "createJiraIssue",
      actionClass: "CREATE",
      target: {
        source_system: "jira",
        resource_type: "User Story",
        container_id: "PKA",
      },
      payload: {
        projectKey: "PKA",
        issueTypeName: "User Story",
        summary: "Stabiliser le viewport du chat",
        description: "Conserver la zone de saisie visible.",
      },
      explanation: "La demande explicite de l’utilisateur correspond à cette création.",
      correlationId: "correlation-123",
    })).resolves.toMatchObject({
      proposalId: "proposal-123",
      decisionToken: "decision-token-123456789012345",
      version: 1,
      state: "PENDING_APPROVAL",
      payload: {
        projectKey: "PKA",
        issueTypeName: "User Story",
        summary: "Stabiliser le viewport du chat",
        description: "Conserver la zone de saisie visible.",
      },
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(init).toMatchObject({
      method: "POST",
      credentials: "include",
      body: JSON.stringify({
        conversation_id: "conversation-123",
        source_system: "jira",
        tool_name: "createJiraIssue",
        action_class: "CREATE",
        target: {
          source_system: "jira",
          resource_type: "User Story",
          container_id: "PKA",
        },
        payload: {
          projectKey: "PKA",
          issueTypeName: "User Story",
          summary: "Stabiliser le viewport du chat",
          description: "Conserver la zone de saisie visible.",
        },
        explanation: "La demande explicite de l’utilisateur correspond à cette création.",
        correlation_id: "correlation-123",
      }),
    });
  });

  it("envoie la version attendue et le token pour approuver ou refuser", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ ...proposalResponse, version: 2, state: "APPROVED" }))
      .mockResolvedValueOnce(jsonResponse({ ...proposalResponse, version: 2, state: "REJECTED" }));

    await approveActionProposal({
      proposalId: "proposal/123",
      expectedVersion: 1,
      decisionToken: "decision-token-123456789012345",
    });
    await rejectActionProposal({
      proposalId: "proposal/123",
      expectedVersion: 2,
      decisionToken: "decision-token-123456789012345",
      reason: "Besoin clarifié",
    });

    expect(fetchMock.mock.calls[0][0]).toBe("https://api.nexia.test/api/actions/proposal%2F123/approve");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        expected_version: 1,
        decision_token: "decision-token-123456789012345",
      }),
    });
    expect(fetchMock.mock.calls[1][0]).toBe("https://api.nexia.test/api/actions/proposal%2F123/reject");
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        expected_version: 2,
        decision_token: "decision-token-123456789012345",
        reason: "Besoin clarifié",
      }),
    });
  });

  it("n’autorise pas une nouvelle tentative après un résultat d’exécution inconnu", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({
      detail: {
        code: "MUTATION_OUTCOME_UNKNOWN",
        message: "Détail interne à ne pas afficher",
      },
    }, 502));

    await expect(executeActionProposal({
      proposalId: "proposal-123",
      expectedVersion: 2,
    })).rejects.toEqual(expect.objectContaining({
      code: "MUTATION_OUTCOME_UNKNOWN",
      message: "L’écriture a été envoyée, mais sa confirmation est inconnue. Vérifiez dans Jira avant toute nouvelle tentative.",
      status: 502,
    }));
  });
});

describe("erreurs publiques", () => {
  it.each([
    [401, "Votre session a expiré. Veuillez vous reconnecter."],
    [403, "Vous n’avez pas l’autorisation d’effectuer cette action."],
    [413, "Ce message est trop long pour être envoyé."],
    [422, "Le message n’a pas pu être validé."],
    [429, "Trop de demandes ont été envoyées. Patientez un instant."],
    [502, "Le service NEXIA est temporairement indisponible."],
    [503, "Le service NEXIA est temporairement indisponible."],
    [504, "Le service NEXIA met trop de temps à répondre."],
    [500, "La demande n’a pas pu être traitée. Réessayez dans un instant."],
  ])("traduit le statut %i sans exposer le corps backend", async (status, message) => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "secret backend detail" }, status));

    const promise = createConversation();

    await expect(promise).rejects.toEqual(expect.objectContaining({
      name: "NexiaApiError",
      message,
      status,
    }));
    await expect(promise).rejects.not.toHaveProperty("message", "secret backend detail");
  });

  it("retourne une erreur sûre quand le réseau est indisponible", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("DNS details"));

    await expect(createConversation()).rejects.toEqual(expect.objectContaining({
      name: "NexiaApiError",
      message: "Le service NEXIA est temporairement inaccessible.",
      status: 0,
    } satisfies Partial<NexiaApiError>));
  });

  it("retourne une erreur sûre pour un JSON invalide", async () => {
    fetchMock.mockResolvedValueOnce(new Response("not-json", { status: 200 }));

    await expect(createConversation()).rejects.toMatchObject({
      message: "La réponse reçue est invalide.",
      status: 200,
    });
  });
});
