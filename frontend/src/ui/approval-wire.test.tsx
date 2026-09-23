import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { askQuestion, nexiaApi } from "@/adapters/nexia-api";

import { MutationApprovalPreview } from "./MutationApprovalPreview";

/**
 * La proposition telle qu'elle arrive REELLEMENT sur le fil, et non telle que je
 * l'avais imaginee.
 *
 * Les tests de l'aperçu partaient d'un objet déjà normalisé — `target: "confluence"`,
 * une charge propre. Le serveur, lui, répond `source_system`, sans objet `target`, et
 * c'est ce que `parseApproval` doit traduire. Un double plus propre que la réalité
 * passe les tests puis échoue à l'écran, ce qui est exactement ce qui s'est produit.
 *
 * Cette forme est relevée sur `ProposedMutationView` du backend, champ par champ.
 */

const CORPS = [
  "| Bloc fonctionnel | Ref. PBS | Userstory | Description | Criteres d'acceptation - Contexte | Criteres d'acceptation - Scenario | Remarques |",
  "| --- | --- | --- | --- | --- | --- | --- |",
  "| Choix du type de frais | | En tant qu'etudiant, je souhaite choisir. | Ecran d'accueil. | Etant donne que le kiosque est sur l'accueil | Lorsque l'etudiant choisit Alors l'ecran suivant s'affiche | |",
].join("\n");

/** La réponse du serveur, mot pour mot dans sa forme. */
const REPONSE_SERVEUR = {
  text: "J’ai préparé le cahier des charges.",
  sources: [],
  approval: {
    id: "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    version: 1,
    decision_token: "decision-token-123456789012345",
    tool_name: "createConfluencePage",
    source_system: "confluence",
    action_class: "CREATE",
    payload: {
      spaceId: "DL",
      title: "Cahier des charges - KIOSQUE K20",
      body: CORPS,
    },
    state: "PENDING_APPROVAL",
    expires_at: "2099-01-01T00:00:00Z",
    explanation: null,
    // La cible du domaine. Elle manquait, et la revision en depend : sans elle,
    // l'interface gardait la correction pour elle seule.
    target: {
      source_system: "confluence",
      resource_type: "page",
      resource_id: null,
      title: "Cahier des charges - KIOSQUE K20",
      container_id: "DL",
      resource_version: null,
    },
  },
};

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("La proposition telle qu'elle arrive du serveur", () => {
  it("conserve le corps de la page jusqu'a l'interface", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(REPONSE_SERVEUR));

    const answer = await askQuestion({
      question: "Genere le cahier des charges du processus KIOSQUE K20.",
      correlationId: "c-1",
      conversationId: "conv-1",
    });

    expect(answer.approval?.payload?.body).toBe(CORPS);
    expect(answer.approval?.payload?.title).toBe("Cahier des charges - KIOSQUE K20");
    expect(answer.approval?.target).toBe("confluence");
  });

  it("affiche le tableau a sept colonnes pour cette proposition", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(REPONSE_SERVEUR));
    const answer = await askQuestion({
      question: "Genere le cahier des charges du processus KIOSQUE K20.",
      correlationId: "c-1",
      conversationId: "conv-1",
    });

    render(
      <MutationApprovalPreview
        approval={answer.approval}
        gateway={{
          approveActionProposal: vi.fn(),
          rejectActionProposal: vi.fn(),
          reviseActionProposal: vi.fn(),
          executeActionProposal: vi.fn(),
        } as never}
      />,
    );

    // Le defaut signale a l'ecran : le panneau s'affichait, sans le tableau.
    const table = screen.getByRole("table");
    expect(table).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")).toHaveLength(7);
  });

  it("envoie la correction au serveur, au lieu de la garder pour elle", async () => {
    /*
     * Le defaut constate a l'ecran : on corrigeait, on approuvait, et la correction
     * disparaissait.
     *
     * La proposition arrivait sans sa cible, que /revise exige. L'interface retombait
     * alors sur une modification gardee dans le navigateur ; le premier retour du
     * serveur la remplacait par la proposition d'origine, qui partait ensuite a
     * l'ecriture. Rien ne le signalait.
     */
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(jsonResponse(REPONSE_SERVEUR));
    const answer = await askQuestion({
      question: "Genere le cahier des charges du processus KIOSQUE K20.",
      correlationId: "c-1",
      conversationId: "conv-1",
    });

    const corrige = CORPS.replace("Ecran d'accueil.", "Ecran d'accueil du kiosque.");
    fetchMock.mockResolvedValueOnce(jsonResponse({
      superseded: { ...REPONSE_SERVEUR.approval, state: "SUPERSEDED", version: 2 },
      replacement: {
        ...REPONSE_SERVEUR.approval,
        id: "3f2504e0-4f89-11d3-9a0c-0305e82c3302",
        version: 1,
        payload: { ...REPONSE_SERVEUR.approval.payload, body: corrige },
      },
      decision_token: "decision-token-223456789012345",
    }));

    render(<MutationApprovalPreview approval={answer.approval} gateway={nexiaApi} />);
    await user.click(screen.getByRole("button", { name: "Modifier la proposition" }));
    const cellule = screen.getByLabelText("Description — ligne 1");
    await user.clear(cellule);
    await user.type(cellule, "Ecran d'accueil du kiosque.");
    await user.click(screen.getByRole("button", { name: "Enregistrer les modifications" }));

    const [url, init] = fetchMock.mock.calls[1];
    expect(String(url)).toContain("/revise");
    const envoye = JSON.parse(String((init as RequestInit).body));
    expect(envoye.payload.body).toContain("Ecran d'accueil du kiosque.");
    expect(envoye.target.source_system).toBe("confluence");
    // Et ce que le serveur rend est ce qui reste a l'ecran.
    expect(screen.getByText("Ecran d'accueil du kiosque.")).toBeInTheDocument();
  });
});
