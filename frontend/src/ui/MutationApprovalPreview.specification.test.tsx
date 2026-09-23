import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type NexiaApproval } from "@/adapters/nexia-api";

import { parseMarkdownTable } from "./markdown-table";

import { MutationApprovalPreview } from "./MutationApprovalPreview";

/**
 * Le cahier des charges dans l'aperçu, et sa modification avant approbation.
 *
 * Deux défauts sont couverts ici, tous deux constatés à l'écran plutôt que déduits.
 *
 * Le corps d'une page n'arrivait même pas jusqu'au composant : l'adaptateur filtrait
 * la charge à quatre champs Jira, si bien qu'un cahier des charges s'affichait vide.
 * Et le bouton « Modifier la proposition » n'était qu'un rappel sans suite — rien ne
 * permettait de corriger une ligne avant d'écrire, ni dans Confluence ni dans Jira.
 */

const CORPS = [
  "| Bloc fonctionnel | Ref. PBS | Userstory | Description | Criteres d'acceptation - Contexte | Criteres d'acceptation - Scenario | Remarques |",
  "| --- | --- | --- | --- | --- | --- | --- |",
  "| Authentification | | En tant qu'utilisateur, je souhaite m'authentifier. | Ouvre l'application. | Etant donne que l'ecran est affiche | Lorsque l'utilisateur valide Alors l'accueil s'affiche | Si iOS : Face ID |",
  "| | | | | Etant donne que l'utilisateur est authentifie | Lorsqu'il ouvre le menu Alors les virements s'affichent | |",
].join("\n");

function pageApproval(): NexiaApproval {
  return {
    target: "confluence",
    actionTarget: { source_system: "confluence", resource_type: "page", title: "Cahier" },
    proposalId: "proposal-cdc",
    decisionToken: "decision-token-123456789012345",
    version: 1,
    state: "PENDING_APPROVAL",
    actionClass: "CREATE",
    payload: { spaceId: "DL", title: "Cahier des charges - KIOSQUE K20", body: CORPS },
  };
}

function gatewayFor(overrides: Record<string, unknown> = {}) {
  return {
    approveActionProposal: vi.fn(),
    rejectActionProposal: vi.fn(),
    reviseActionProposal: vi.fn(),
    executeActionProposal: vi.fn(),
    ...overrides,
  } as never;
}

function revisionRendant(payload: Record<string, unknown>) {
  return vi.fn().mockResolvedValue({
    replacement: {
      target: "confluence",
      proposalId: "proposal-cdc-2",
      decisionToken: "decision-token-223456789012345",
      version: 1,
      state: "PENDING_APPROVAL",
      payload,
    },
    decisionToken: "decision-token-223456789012345",
  });
}

describe("Le cahier des charges tel qu'il sera publie", () => {
  it("rend le corps en tableau plutot qu'en barres verticales", () => {
    render(<MutationApprovalPreview approval={pageApproval()} gateway={gatewayFor()} />);

    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader")).toHaveLength(7);
    expect(within(table).getByRole("columnheader", { name: "Bloc fonctionnel" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Remarques" })).toBeInTheDocument();
    expect(within(table).getByText("Si iOS : Face ID")).toBeInTheDocument();
  });

  it("dit combien de blocs seront ecrits", () => {
    // Un relecteur doit pouvoir juger le regroupement d'un coup d'oeil : quinze
    // blocs pour un processus qui en compte trois est le defaut le plus courant.
    render(<MutationApprovalPreview approval={pageApproval()} gateway={gatewayFor()} />);

    expect(screen.getByText(/1 bloc\(s\) fonctionnel\(s\)/)).toBeInTheDocument();
    expect(screen.getByText(/2 ligne\(s\)/)).toBeInTheDocument();
  });

  it("montre le titre de la page et son espace", () => {
    render(<MutationApprovalPreview approval={pageApproval()} gateway={gatewayFor()} />);

    expect(screen.getByText("Cahier des charges - KIOSQUE K20")).toBeInTheDocument();
    expect(screen.getByText("DL")).toBeInTheDocument();
  });

  it("montre le texte brut quand le corps ne contient aucun tableau", () => {
    // La consigne interdit la prose. La cacher priverait le relecteur du defaut.
    const approval = pageApproval();

    render(
      <MutationApprovalPreview
        approval={{ ...approval, payload: { ...approval.payload, body: "Un cahier en prose." } }}
        gateway={gatewayFor()}
      />,
    );

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("Un cahier en prose.")).toBeInTheDocument();
  });
});

describe("Corriger avant d'ecrire", () => {
  it("enregistre une modification du corps comme une revision", async () => {
    const user = userEvent.setup();
    const reviseActionProposal = revisionRendant({ spaceId: "DL", title: "Corrige", body: CORPS });

    render(
      <MutationApprovalPreview
        approval={pageApproval()}
        gateway={gatewayFor({ reviseActionProposal })}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Modifier la proposition" }));
    const titre = screen.getByLabelText("Titre de la page");
    await user.clear(titre);
    await user.type(titre, "Corrige");
    await user.click(screen.getByRole("button", { name: "Enregistrer les modifications" }));

    expect(reviseActionProposal).toHaveBeenCalledTimes(1);
    const envoye = reviseActionProposal.mock.calls[0][0];
    expect(envoye.proposalId).toBe("proposal-cdc");
    expect(envoye.payload.title).toBe("Corrige");
    // La charge entiere est renvoyee. Une cle perdue ici serait une cle effacee de
    // l'ecriture -- un espace, un identifiant de page.
    expect(envoye.payload.spaceId).toBe("DL");
    expect(envoye.payload.body).toBe(CORPS);
  });

  it("repart du jeton neuf apres une revision", async () => {
    // Le serveur ne modifie pas une proposition en place : il la remplace. Reutiliser
    // l'ancien jeton ferait echouer l'approbation suivante avec un conflit que
    // personne ne saurait expliquer.
    const user = userEvent.setup();
    const approveActionProposal = vi.fn().mockResolvedValue({
      target: "confluence",
      proposalId: "proposal-cdc-2",
      version: 2,
      state: "APPROVED",
    });
    const reviseActionProposal = revisionRendant({ spaceId: "DL", title: "Corrige", body: CORPS });

    render(
      <MutationApprovalPreview
        approval={pageApproval()}
        gateway={gatewayFor({ reviseActionProposal, approveActionProposal })}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Modifier la proposition" }));
    await user.click(screen.getByRole("button", { name: "Enregistrer les modifications" }));
    await user.click(screen.getByRole("button", { name: "Approuver" }));

    expect(approveActionProposal).toHaveBeenCalledWith({
      proposalId: "proposal-cdc-2",
      expectedVersion: 1,
      decisionToken: "decision-token-223456789012345",
    });
  });

  it("annule une modification sans rien envoyer", async () => {
    const user = userEvent.setup();
    const reviseActionProposal = vi.fn();

    render(
      <MutationApprovalPreview
        approval={pageApproval()}
        gateway={gatewayFor({ reviseActionProposal })}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Modifier la proposition" }));
    await user.type(screen.getByLabelText("Titre de la page"), " modifie");
    await user.click(screen.getByRole("button", { name: "Annuler" }));

    expect(reviseActionProposal).not.toHaveBeenCalled();
    expect(screen.getByText("Cahier des charges - KIOSQUE K20")).toBeInTheDocument();
  });

  it("interdit d'approuver pendant qu'on modifie", async () => {
    // Le bouton porterait sur un texte que le serveur ne connait pas encore.
    const user = userEvent.setup();

    render(<MutationApprovalPreview approval={pageApproval()} gateway={gatewayFor()} />);

    await user.click(screen.getByRole("button", { name: "Modifier la proposition" }));

    expect(screen.getByRole("button", { name: /Approuver/ })).toBeDisabled();
  });

  it("laisse aussi corriger un ticket Jira avant l'ecriture", async () => {
    const user = userEvent.setup();
    const reviseActionProposal = revisionRendant({ projectKey: "KAN" });

    render(
      <MutationApprovalPreview
        approval={{
          target: "jira",
          actionTarget: { source_system: "jira", resource_type: "issue" },
          proposalId: "proposal-jira",
          decisionToken: "decision-token-123456789012345",
          version: 1,
          state: "PENDING_APPROVAL",
          actionClass: "CREATE",
          payload: {
            projectKey: "KAN",
            issueTypeName: "Tache",
            summary: "Export CSV",
            description: "Manquant.",
          },
        }}
        gateway={gatewayFor({ reviseActionProposal })}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Modifier la proposition" }));
    const titre = screen.getByLabelText("Titre du ticket");
    await user.clear(titre);
    await user.type(titre, "Export CSV absent");
    await user.click(screen.getByRole("button", { name: "Enregistrer les modifications" }));

    expect(reviseActionProposal.mock.calls[0][0].payload).toMatchObject({
      projectKey: "KAN",
      summary: "Export CSV absent",
      description: "Manquant.",
    });
  });
});

describe("Corriger dans le tableau", () => {
  /**
   * Le markdown brut obligeait à retrouver sa ligne en comptant des barres
   * verticales, sous un aperçu qui, lui, était lisible. On corrige maintenant la
   * cellule là où on la lit.
   */

  it("garde le tableau a l'ecran pendant la modification", async () => {
    const user = userEvent.setup();

    render(<MutationApprovalPreview approval={pageApproval()} gateway={gatewayFor()} />);
    await user.click(screen.getByRole("button", { name: "Modifier la proposition" }));

    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader")).toHaveLength(7);
    // Sept colonnes sur deux lignes : chaque cellule est un champ.
    expect(within(table).getAllByRole("textbox")).toHaveLength(14);
  });

  it("n'expose plus le markdown brut quand le corps est un tableau", async () => {
    const user = userEvent.setup();

    render(<MutationApprovalPreview approval={pageApproval()} gateway={gatewayFor()} />);
    await user.click(screen.getByRole("button", { name: "Modifier la proposition" }));

    expect(screen.queryByLabelText("Corps de la page en markdown")).not.toBeInTheDocument();
  });

  it("garde le markdown brut quand il n'y a pas de tableau a corriger", async () => {
    // Un corps en prose est justement le defaut a reprendre : sans champ, il ne
    // resterait qu'a refuser la proposition.
    const user = userEvent.setup();
    const approval = pageApproval();

    render(
      <MutationApprovalPreview
        approval={{ ...approval, payload: { ...approval.payload, body: "En prose." } }}
        gateway={gatewayFor()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Modifier la proposition" }));

    expect(screen.getByLabelText("Corps de la page en markdown")).toBeInTheDocument();
  });

  it("envoie le corps recompose a partir de la cellule corrigee", async () => {
    const user = userEvent.setup();
    const reviseActionProposal = revisionRendant({ spaceId: "DL", title: "Cahier", body: CORPS });

    render(
      <MutationApprovalPreview
        approval={pageApproval()}
        gateway={gatewayFor({ reviseActionProposal })}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Modifier la proposition" }));
    const cellule = screen.getByLabelText("Remarques — ligne 1");
    await user.clear(cellule);
    await user.type(cellule, "Android uniquement");
    await user.click(screen.getByRole("button", { name: "Enregistrer les modifications" }));

    const envoye = reviseActionProposal.mock.calls[0][0].payload.body as string;
    expect(envoye).toContain("Android uniquement");
    expect(envoye).not.toContain("Face ID");
    // Les six autres colonnes de la ligne sont intactes, et la ligne de
    // continuation avec : recomposer le corps ne doit rien perdre en passant.
    const relu = parseMarkdownTable(envoye)!;
    expect(relu.headers).toHaveLength(7);
    expect(relu.rows).toHaveLength(2);
    expect(relu.rows[0][2]).toBe("En tant qu'utilisateur, je souhaite m'authentifier.");
    expect(relu.rows[1].slice(0, 4)).toEqual(["", "", "", ""]);
  });

  it("ne laisse pas renommer les colonnes", async () => {
    // Les sept colonnes sont celles de la page de l'equipe. En renommer une ici ne
    // changerait pas le gabarit, et ferait diverger cette page des autres.
    const user = userEvent.setup();

    render(<MutationApprovalPreview approval={pageApproval()} gateway={gatewayFor()} />);
    await user.click(screen.getByRole("button", { name: "Modifier la proposition" }));

    const entete = screen.getByRole("columnheader", { name: "Bloc fonctionnel" });
    expect(within(entete).queryByRole("textbox")).toBeNull();
  });
});

describe("La largeur du panneau", () => {
  it("s'elargit quand il porte un tableau", () => {
    // Sept colonnes ne tiennent pas dans les 500 px d'une bulle de conversation :
    // le tableau s'affichait tronque a la quatrieme colonne.
    const { container } = render(
      <MutationApprovalPreview approval={pageApproval()} gateway={gatewayFor()} />,
    );

    expect(container.querySelector(".approval-panel--wide")).not.toBeNull();
  });

  it("garde sa largeur pour un ticket", () => {
    // Elargir un ticket a trois champs laisserait une bande vide a parcourir.
    const { container } = render(
      <MutationApprovalPreview
        approval={{
          target: "jira",
          proposalId: "p1",
          decisionToken: "decision-token-123456789012345",
          version: 1,
          state: "PENDING_APPROVAL",
          payload: { projectKey: "KAN", summary: "Export CSV" },
        }}
        gateway={gatewayFor()}
      />,
    );

    expect(container.querySelector(".approval-panel--wide")).toBeNull();
  });

  it("garde sa largeur quand le corps n'est pas un tableau", () => {
    const approval = pageApproval();
    const { container } = render(
      <MutationApprovalPreview
        approval={{ ...approval, payload: { ...approval.payload, body: "En prose." } }}
        gateway={gatewayFor()}
      />,
    );

    expect(container.querySelector(".approval-panel--wide")).toBeNull();
  });
});
