import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { NexiaApiError, type NexiaApproval } from "@/adapters/nexia-api";

import { MutationApprovalPreview } from "./MutationApprovalPreview";

describe("MutationApprovalPreview", () => {
  it("présente le contenu exact, la cible et les garde-fous de l’écriture", () => {
    render(<MutationApprovalPreview />);

    expect(screen.getByRole("heading", { name: "Créer un ticket" })).toBeInTheDocument();
    expect(screen.getByText("Jira · Backlog PKA")).toBeInTheDocument();
    expect(screen.getByText("Stabiliser le viewport du chat")).toBeInTheDocument();
    expect(screen.getByText("Permission")).toBeInTheDocument();
    expect(screen.getByText("Permission").parentElement).toHaveTextContent("Vérifiée");
    expect(screen.getByText("Aucune écriture n’est envoyée tant que vous n’avez pas confirmé.")).toBeInTheDocument();
  });

  it("permet de parcourir les destinations et de prendre une décision locale", async () => {
    const user = userEvent.setup();
    render(<MutationApprovalPreview />);

    await user.click(screen.getByRole("button", { name: "Confluence" }));
    expect(screen.getByRole("heading", { name: "Créer une page" })).toBeInTheDocument();
    expect(screen.getByText("Parcours d’approbation des mutations")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Approuver et créer" }));
    expect(screen.getByRole("status")).toHaveTextContent("Action approuvée");
    expect(screen.queryByRole("button", { name: "Approuver et créer" })).not.toBeInTheDocument();
  });

  it("affiche un refus sans suggérer qu’une mutation a été exécutée", async () => {
    const user = userEvent.setup();
    render(<MutationApprovalPreview target="figma" />);

    await user.click(screen.getByRole("button", { name: "Refuser" }));

    expect(screen.getByRole("status")).toHaveTextContent("Action refusée");
    expect(screen.getByRole("status")).toHaveTextContent("Aucune donnée ne sera écrite.");
  });

  it("enchaîne approbation puis exécution pour une proposition distante", async () => {
    const user = userEvent.setup();
    const approval: NexiaApproval = {
      target: "jira",
      proposalId: "proposal-123",
      decisionToken: "decision-token-123456789012345",
      version: 1,
      state: "PENDING_APPROVAL",
      actionClass: "CREATE",
      action: "Créer un ticket",
      destination: "Jira · PKA",
      objectType: "User Story",
      project: "PKA",
      payload: {
        projectKey: "PKA",
        issueTypeName: "User Story",
        summary: "Stabiliser le viewport du chat",
        description: "Conserver la zone de saisie visible.",
      },
    };
    const gateway = {
      approveActionProposal: vi.fn().mockResolvedValue({
        ...approval,
        version: 2,
        state: "APPROVED",
      }),
      rejectActionProposal: vi.fn(),
      reviseActionProposal: vi.fn(),
      executeActionProposal: vi.fn().mockResolvedValue({
        succeeded: true,
        partial: false,
        externalIds: ["KAN-42"],
      }),
    };

    render(<MutationApprovalPreview approval={approval} gateway={gateway} />);

    await user.click(screen.getByRole("button", { name: "Approuver" }));
    expect(gateway.approveActionProposal).toHaveBeenCalledWith({
      proposalId: "proposal-123",
      expectedVersion: 1,
      decisionToken: "decision-token-123456789012345",
    });
    expect(await screen.findByRole("button", { name: "Exécuter l’écriture" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Exécuter l’écriture" }));
    expect(gateway.executeActionProposal).toHaveBeenCalledWith({
      proposalId: "proposal-123",
      expectedVersion: 2,
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Ticket créé : KAN-42.");
  });

  it("masque entièrement l’interface d’écriture quand les mutations sont désactivées", async () => {
    const user = userEvent.setup();
    const approval: NexiaApproval = {
      target: "jira",
      proposalId: "proposal-123",
      decisionToken: "decision-token-123456789012345",
      version: 1,
      state: "PENDING_APPROVAL",
      payload: { projectKey: "PKA", summary: "Ticket confidentiel" },
    };
    const gateway = {
      approveActionProposal: vi.fn().mockRejectedValue(new NexiaApiError(
        "Les écritures externes sont désactivées dans cet environnement.",
        403,
        "MCP_MUTATIONS_DISABLED",
      )),
      rejectActionProposal: vi.fn(),
      reviseActionProposal: vi.fn(),
      executeActionProposal: vi.fn(),
    };

    render(<MutationApprovalPreview approval={approval} gateway={gateway} />);
    await user.click(screen.getByRole("button", { name: "Approuver" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Écritures désactivées");
    expect(screen.queryByText("Ticket confidentiel")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approuver" })).not.toBeInTheDocument();
  });
});
