"use client";

import { createHttpAssistantGateway } from "./adapters/http-assistant-gateway";
import { demoAssistantGateway } from "./adapters/demo-assistant-gateway";
import type { ProjectAssistantGateway } from "./application/assistant-gateway";
import type { ProjectAssistantSnapshot } from "./domain/models";
import {
  demoActionProposal,
  demoConnectors,
  demoMessages,
  demoRequests,
  demoSession,
} from "./demo/fixtures";
import { AssistantWorkspace } from "./ui/assistant-workspace";

// Read statically, because Next.js inlines `NEXT_PUBLIC_*` at build time and a
// computed key would resolve to nothing.
const API_URL = process.env.NEXT_PUBLIC_ASSISTANT_API_URL;
const TENANT_ID = process.env.NEXT_PUBLIC_ASSISTANT_TENANT_ID;
const USER_ID = process.env.NEXT_PUBLIC_ASSISTANT_USER_ID;

/**
 * The single composition point: it decides which adapter the screen talks to.
 *
 * Falling back to the demo when the backend address is absent is deliberate --
 * a build with no backend configured must not offer an assistant that fails on
 * every message. The three values are required together: a partial configuration
 * would send requests without the headers the backend derives the tenant from,
 * and every one of them would be refused.
 *
 * The tenant and the user come from the environment because this build
 * authenticates nobody. That is the backend's `dev_headers` mode, which its own
 * settings forbid in production -- so this configuration cannot be shipped as is,
 * and the seam to replace when identity arrives is here.
 */
function selectGateway(): ProjectAssistantGateway {
  if (!API_URL || !TENANT_ID || !USER_ID) return demoAssistantGateway;
  return createHttpAssistantGateway({
    baseUrl: API_URL.replace(/\/+$/, ""),
    tenantId: TENANT_ID,
    userId: USER_ID,
  });
}

// The navigator, the connectors and the pending action still come from fixtures:
// no endpoint serves them. Only the conversation is live, and only when the
// backend address is configured.
const snapshot: ProjectAssistantSnapshot = {
  action: demoActionProposal,
  connectors: demoConnectors,
  messages: demoMessages,
  requests: demoRequests,
  session: demoSession,
};

export function ProjectAssistantScreen() {
  return <AssistantWorkspace gateway={selectGateway()} initial={snapshot} />;
}
