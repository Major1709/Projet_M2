"use client";

import { demoAssistantGateway } from "../adapters/demo-assistant-gateway";
import type { ProjectAssistantSnapshot } from "../domain/models";
import { AssistantWorkspace } from "../ui/assistant-workspace";
import {
  demoActionProposal,
  demoConnectors,
  demoMessages,
  demoRequests,
  demoSession,
} from "./fixtures";

const demoSnapshot: ProjectAssistantSnapshot = {
  action: demoActionProposal,
  connectors: demoConnectors,
  messages: demoMessages,
  requests: demoRequests,
  session: demoSession,
};

/** Public demo entry point. Next.js only needs to know this interface. */
export function ProjectAssistantDemo() {
  return <AssistantWorkspace gateway={demoAssistantGateway} initial={demoSnapshot} />;
}
