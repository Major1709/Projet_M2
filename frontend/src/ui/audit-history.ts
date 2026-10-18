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
