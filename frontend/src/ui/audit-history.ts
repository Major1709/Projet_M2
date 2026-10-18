/**
 * L'historique des changements, mis en mots.
 *
 * Le serveur rend des constantes — `MUTATION_EXECUTED`, `createConfluencePage` — qui
 * sont justes et illisibles. La traduction vit ici, à part du composant, pour être
 * testée sans DOM.
 *
 * Un type inconnu est rendu tel quel plutôt que masqué ou remplacé par « Autre » :
 * le jour où le backend ajoute un événement, mieux vaut une ligne brute qu'une ligne
 * absente dans une liste dont tout l'intérêt est d'être complète.
 */

import { type NexiaAuditEvent } from "@/adapters/nexia-api";

const LABELS: Record<string, string> = {
  ACTION_PROPOSED: "Écriture proposée",
  ACTION_APPROVED: "Approuvée",
  ACTION_REJECTED: "Refusée",
  ACTION_REVISED: "Corrigée avant écriture",
  MUTATION_DISPATCHED: "Envoyée",
  MUTATION_EXECUTED: "Écrite",
  MUTATION_FAILED: "Échec de l'écriture",
};

export function labelOf(eventType: string): string {
  return LABELS[eventType] ?? eventType;
}

const SYSTEMS: Record<string, string> = {
  jira: "Jira",
  confluence: "Confluence",
  figma: "Figma",
};

/**
 * Ce que l'écriture visait, quand l'événement le dit.
 *
 * Chaîne vide plutôt que « inconnu » : une approbation ne porte pas toujours le
 * système, et écrire « inconnu » à l'écran ferait passer une absence de détail pour
 * un défaut.
 */
export function targetOf(event: NexiaAuditEvent): string {
  const systeme = event.sourceSystem ? SYSTEMS[event.sourceSystem] ?? event.sourceSystem : "";
  if (systeme && event.actionClass === "CREATE") return `Création · ${systeme}`;
  if (systeme && event.actionClass === "UPDATE") return `Modification · ${systeme}`;
  return systeme;
}

/**
 * La date, en toutes lettres et dans le fuseau du lecteur.
 *
 * Une date que le navigateur ne sait pas lire est rendue telle quelle : la valeur
 * brute reste vérifiable, là où un tiret ne dirait rien.
 */
export function momentOf(occurredAt: string): string {
  const date = new Date(occurredAt);
  if (Number.isNaN(date.getTime())) return occurredAt;
  return date.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const OBJETS: Record<string, string> = {
  page: "une page",
  issue: "un ticket",
};

const ACTIONS: Record<string, string> = {
  CREATE: "créer",
  UPDATE: "modifier",
  DELETE: "supprimer",
};

/**
 * Ce que l'événement raconte, en une phrase.
 *
 * L'historique affichait « Écrite · Création · Jira » : trois fragments justes qui
 * obligent le lecteur à les recoller lui-même. Une ligne d'historique sert à
 * retrouver ce qui s'est passé — elle doit pouvoir se lire d'un trait.
 *
 * Composée à partir de champs et jamais d'un texte stocké : le titre vient de la
 * proposition, la nature de l'événement, et le système du contrat. Une phrase
 * écrite au moment de l'audit aurait figé une formulation et une langue.
 *
 * Chaîne vide quand il n'y a rien d'utile à dire — un événement sans ressource ni
 * système se lit alors sous son seul libellé, ce qui vaut mieux qu'une phrase creuse.
 */
/**
 * Qui a agi, en tete de phrase.
 *
 * « Vous » quand c'est la personne qui regarde — tranché par le serveur, qui compare
 * des identifiants et non des noms : deux personnes peuvent porter le même.
 *
 * Chaîne vide quand le nom est inconnu. L'action se raconte alors sans sujet plutôt
 * qu'avec un sujet inventé : attribuer une écriture à quelqu'un est précisément ce
 * qu'un historique ne doit pas faire à la légère.
 */
function auteurOf(event: NexiaAuditEvent): string {
  if (event.byYou) return "Vous";
  return event.actorName ?? "";
}

/**
 * Une décision humaine : « Vous avez approuvé X », « Fanny a refusé X ».
 *
 * Sans auteur connu, la forme devient impersonnelle — « Approuvé : X ». Elle dit
 * toujours ce qui s'est passé, et s'abstient de dire par qui.
 */
function decide(
  event: NexiaAuditEvent,
  participe: string,
  nomme: string,
  quoi: string,
): string {
  const objet = nomme || quoi;
  const suffixe = event.eventType === "ACTION_REVISED" ? " avant écriture" : "";
  const auteur = auteurOf(event);
  if (!auteur) {
    const majuscule = participe.charAt(0).toUpperCase() + participe.slice(1);
    return `${majuscule} : ${objet}${suffixe}`;
  }
  const verbe = auteur === "Vous" ? "avez" : "a";
  return `${auteur} ${verbe} ${participe} ${objet}${suffixe}`;
}

export function describe(event: NexiaAuditEvent): string {
  const objet = event.resourceType ? OBJETS[event.resourceType] ?? "un élément" : "";
  const systeme = event.sourceSystem ? SYSTEMS[event.sourceSystem] ?? event.sourceSystem : "";
  const verbe = event.actionClass ? ACTIONS[event.actionClass] : undefined;
  const nomme = event.resourceTitle ? `« ${event.resourceTitle} »` : "";

  // "créer une page Confluence" : le sujet de l'action, independamment de son sort.
  const quoi = [verbe, objet, systeme].filter(Boolean).join(" ");
  if (!quoi && !nomme) return "";

  switch (event.eventType) {
    case "ACTION_PROPOSED":
      return nomme ? `Proposition de ${quoi} : ${nomme}` : `Proposition de ${quoi}`;
    case "ACTION_APPROVED":
      return decide(event, "approuvé", nomme, quoi);
    case "ACTION_REJECTED":
      return decide(event, "refusé", nomme, quoi);
    case "ACTION_REVISED":
      return decide(event, "corrigé", nomme, quoi);
    case "MUTATION_DISPATCHED":
      return nomme ? `Envoi de ${nomme} vers ${systeme || "la source"}` : `Envoi vers ${systeme}`;
    case "MUTATION_EXECUTED":
      return nomme ? `${nomme} écrit dans ${systeme || "la source"}` : `Écrit dans ${systeme}`;
    case "MUTATION_FAILED":
      return nomme
        ? `L'écriture de ${nomme} a échoué`
        : `L'écriture a échoué${systeme ? ` dans ${systeme}` : ""}`;
    default:
      return quoi;
  }
}
