import { describe, expect, it } from "vitest";

import { type NexiaAuditEvent } from "@/adapters/nexia-api";

import { describe as decrire, labelOf, momentOf, targetOf } from "./audit-history";

function evenement(changes: Partial<NexiaAuditEvent> = {}): NexiaAuditEvent {
  return {
    id: "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    eventType: "MUTATION_EXECUTED",
    occurredAt: "2026-09-27T14:30:00Z",
    externalIds: [],
    byYou: true,
    ...changes,
  };
}

describe("labelOf", () => {
  it("met les constantes du serveur en francais", () => {
    expect(labelOf("ACTION_PROPOSED")).toBe("Écriture proposée");
    expect(labelOf("MUTATION_EXECUTED")).toBe("Écrite");
    expect(labelOf("MUTATION_FAILED")).toBe("Échec de l'écriture");
  });

  it("rend un type inconnu tel quel plutot que de le masquer", () => {
    // Le jour ou le backend ajoute un evenement, mieux vaut une ligne brute qu'une
    // ligne absente dans une liste dont l'interet est d'etre complete.
    expect(labelOf("QUELQUE_CHOSE_DE_NEUF")).toBe("QUELQUE_CHOSE_DE_NEUF");
  });
});

describe("targetOf", () => {
  it("dit ce que l'ecriture visait", () => {
    expect(targetOf(evenement({ sourceSystem: "confluence", actionClass: "CREATE" })))
      .toBe("Création · Confluence");
    expect(targetOf(evenement({ sourceSystem: "jira", actionClass: "UPDATE" })))
      .toBe("Modification · Jira");
  });

  it("se tait quand l'evenement ne le dit pas", () => {
    // Une approbation ne porte pas toujours le systeme. Ecrire "inconnu" ferait
    // passer une absence de detail pour un defaut.
    expect(targetOf(evenement())).toBe("");
    expect(targetOf(evenement({ sourceSystem: "jira" }))).toBe("Jira");
  });
});

describe("momentOf", () => {
  it("rend une date lisible", () => {
    expect(momentOf("2026-09-27T14:30:00Z")).toMatch(/27\/09\/2026/);
  });

  it("rend la valeur brute quand elle n'est pas une date", () => {
    // Elle reste verifiable, la ou un tiret ne dirait rien.
    expect(momentOf("pas-une-date")).toBe("pas-une-date");
  });
});

describe("describe", () => {
  /**
   * L'historique affichait « Écrite · Création · Jira » : trois fragments justes qui
   * obligeaient le lecteur a les recoller lui-meme.
   */

  it("raconte une ecriture reussie", () => {
    expect(
      decrire(
        evenement({
          eventType: "MUTATION_EXECUTED",
          sourceSystem: "confluence",
          resourceType: "page",
          resourceTitle: "CDCF K20",
          actionClass: "CREATE",
        }),
      ),
    ).toBe("« CDCF K20 » écrit dans Confluence");
  });

  it("dit qui a tranche, parce que c'est la question qu'on se pose", () => {
    const approuve = evenement({
      eventType: "ACTION_APPROVED",
      resourceTitle: "CDCF K20",
      resourceType: "page",
      sourceSystem: "confluence",
      actionClass: "CREATE",
    });

    expect(decrire(approuve)).toBe("Vous avez approuvé « CDCF K20 »");
    expect(decrire({ ...approuve, eventType: "ACTION_REJECTED" })).toBe(
      "Vous avez refusé « CDCF K20 »",
    );
  });

  it("nomme l'action proposee quand rien n'a encore ete ecrit", () => {
    expect(
      decrire(
        evenement({
          eventType: "ACTION_PROPOSED",
          sourceSystem: "jira",
          resourceType: "issue",
          actionClass: "CREATE",
          resourceTitle: "Export CSV manquant",
        }),
      ),
    ).toBe("Proposition de créer un ticket Jira : « Export CSV manquant »");
  });

  it("se passe du titre quand la proposition n'en portait pas", () => {
    // Un evenement sans ressource doit rester lisible plutot que disparaitre.
    expect(
      decrire(
        evenement({
          eventType: "MUTATION_EXECUTED",
          sourceSystem: "jira",
          actionClass: "CREATE",
          resourceType: "issue",
        }),
      ),
    ).toBe("Écrit dans Jira");
  });

  it("ne dit rien plutot qu'une phrase creuse", () => {
    // L'evenement se lira alors sous son seul libelle.
    expect(decrire(evenement({ eventType: "ACTION_APPROVED" }))).toBe("");
  });

  it("signale un echec comme un echec", () => {
    expect(
      decrire(
        evenement({
          eventType: "MUTATION_FAILED",
          resourceTitle: "CDCF K20",
          resourceType: "page",
          sourceSystem: "confluence",
          actionClass: "CREATE",
        }),
      ),
    ).toBe("L'écriture de « CDCF K20 » a échoué");
  });
});

describe("l'auteur de la decision", () => {
  /**
   * Sur un outil qui ecrit dans Jira et Confluence AU NOM de quelqu'un, savoir qui a
   * approuve est la question qui vient juste apres "qu'est-ce qui a ete ecrit".
   */

  const APPROBATION = {
    eventType: "ACTION_APPROVED",
    resourceTitle: "CDCF K20",
    resourceType: "page",
    sourceSystem: "confluence",
    actionClass: "CREATE",
  };

  it("dit « Vous » pour la personne qui regarde", () => {
    expect(decrire(evenement({ ...APPROBATION, byYou: true }))).toBe(
      "Vous avez approuvé « CDCF K20 »",
    );
  });

  it("nomme quelqu'un d'autre", () => {
    expect(
      decrire(evenement({ ...APPROBATION, byYou: false, actorName: "Fanny Andrianaly" })),
    ).toBe("Fanny Andrianaly a approuvé « CDCF K20 »");
  });

  it("raconte sans sujet quand l'auteur est inconnu", () => {
    // Attribuer une ecriture a quelqu'un est precisement ce qu'un historique ne doit
    // pas faire a la legere.
    expect(decrire(evenement({ ...APPROBATION, byYou: false }))).toBe(
      "Approuvé : « CDCF K20 »",
    );
  });

  it("accorde le verbe a l'auteur", () => {
    const refus = { ...APPROBATION, eventType: "ACTION_REJECTED" };

    expect(decrire(evenement({ ...refus, byYou: true }))).toContain("Vous avez refusé");
    expect(decrire(evenement({ ...refus, byYou: false, actorName: "Paul" }))).toContain(
      "Paul a refusé",
    );
  });

  it("garde la precision d'une correction", () => {
    expect(
      decrire(evenement({ ...APPROBATION, eventType: "ACTION_REVISED", byYou: true })),
    ).toBe("Vous avez corrigé « CDCF K20 » avant écriture");
  });
});
