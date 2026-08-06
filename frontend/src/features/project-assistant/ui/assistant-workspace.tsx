"use client";

import type { ProjectAssistantGateway } from "../application/assistant-gateway";
import { useAssistantWorkspace } from "../application/use-assistant-workspace";
import type { ProjectAssistantSnapshot } from "../domain/models";
import { ApprovalPanel } from "./approval-panel";
import { ChatConversation } from "./chat-conversation";
import { ChevronIcon, MessageIcon, MoreIcon, SparklesIcon } from "./icons";
import { RequestNavigator } from "./request-navigator";

interface AssistantWorkspaceProps {
  gateway: ProjectAssistantGateway;
  initial: ProjectAssistantSnapshot;
}

/** Presentation implementation; state transitions live in the application module. */
export function AssistantWorkspace({ gateway, initial }: AssistantWorkspaceProps) {
  const workspace = useAssistantWorkspace(initial, gateway);

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#main-workspace" aria-label="Nexus, aller au contenu principal">
          <span className="brand-mark" aria-hidden="true">
            <SparklesIcon width={21} height={21} />
          </span>
          <span>
            <strong>Nexus</strong>
            <small>Project intelligence</small>
          </span>
        </a>

        <div className="project-switcher" aria-label="Projet actif">
          <span className="project-monogram" aria-hidden="true">PC</span>
          <span>
            <small>Projet actif</small>
            <strong>{initial.session.workspace}</strong>
          </span>
          <ChevronIcon className="chevron-down" width={16} height={16} />
        </div>

        <div className="connector-strip" aria-label="État simulé des connecteurs">
          {initial.connectors.map((connector) => (
            <span className="connector" key={connector.system} title={connector.detail}>
              <span className={`connector-dot connector-dot--${connector.state}`} aria-hidden="true" />
              {connector.label}
            </span>
          ))}
        </div>

        <div className="demo-banner" role="note">Prototype · données fictives</div>

        <button className="icon-button" type="button" aria-label="Plus d’options" disabled>
          <MoreIcon />
        </button>
        <div className="profile">
          <span className="profile-avatar" aria-hidden="true">{initial.session.initials}</span>
          <span className="profile-copy">
            <strong>{initial.session.name}</strong>
            <small>{initial.session.role}</small>
          </span>
        </div>
      </header>

      <nav className="workspace-tabs" aria-label="Navigation principale">
        <a className="workspace-tab is-active" href="#main-workspace" aria-current="page">
          <MessageIcon width={17} height={17} /> Assistant
        </a>
        <button className="workspace-tab" type="button" disabled>Connaissances</button>
        <button className="workspace-tab" type="button" disabled>Synchronisations</button>
        <button className="workspace-tab" type="button" disabled>Audit</button>
      </nav>

      {workspace.error ? (
        <div className="workspace-error" role="alert">
          {workspace.error}
        </div>
      ) : null}

      <div className="workspace-grid" id="main-workspace">
        <RequestNavigator
          requests={workspace.requests}
          selectedIds={workspace.selectedIds}
          isIndexing={workspace.isIndexing}
          onToggle={workspace.toggleRequest}
          onIndex={() => void workspace.indexSelectedRequests()}
        />
        <ChatConversation
          messages={workspace.messages}
          isResponding={workspace.isResponding}
          onSend={workspace.sendMessage}
        />
        <ApprovalPanel
          action={workspace.action}
          feedback={workspace.decisionFeedback}
          busyDecision={workspace.busyDecision}
          onDecision={workspace.decideAction}
          onReset={workspace.resetAction}
        />
      </div>
    </div>
  );
}
