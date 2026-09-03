const DEFAULT_API_BASE_URL = "http://localhost:8000";

export type NexiaSource = {
  title: string;
  url?: string;
  provider?: string;
  retrievedAt?: string;
  truncated?: boolean;
};

export type NexiaAnswer = {
  answer: string;
  sources: NexiaSource[];
};

type ConversationResponse = {
  id?: unknown;
};

type QuestionResponse = {
  text?: unknown;
  sources?: unknown;
};

export type NexiaGateway = {
  createConversation: (signal?: AbortSignal) => Promise<string>;
  askQuestion: (input: {
    question: string;
    correlationId: string;
    conversationId: string;
    signal?: AbortSignal;
  }) => Promise<NexiaAnswer>;
  signOut: () => Promise<void>;
};

export class NexiaApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
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
      messageByStatus[response.status]
        ?? "La demande n’a pas pu être traitée. Réessayez dans un instant.",
      response.status,
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

  return {
    answer,
    sources: parseSources(payload.sources),
  };
}

export async function signOut(): Promise<void> {
  await request("/api/auth/atlassian/signout", { method: "POST" });
}

export const nexiaApi: NexiaGateway = {
  createConversation,
  askQuestion,
  signOut,
};
