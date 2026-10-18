/**
 * Nommer une source que la lecture n'a pas su nommer.
 *
 * Quand NEXIA lit une ressource précise, le serveur rend son titre — « CDCF K20 »,
 * « KAN-39 — Suivi de projet ». Mais une recherche ne désigne rien : elle n'a pas de
 * titre, et c'est volontaire, la nommer d'après son premier résultat laisserait
 * croire qu'une seule page a été consultée.
 *
 * Restait le nom de l'outil, affiché tel quel : « searchJiraIssuesUsingJql ». Il dit
 * *comment* la lecture a été faite, jamais *ce qui* a été lu, et il est écrit pour
 * une machine. Ce module le traduit.
 *
 * Un outil inconnu garde son nom : le jour où le registre en ajoute un, mieux vaut
 * une source au nom technique qu'une source appelée « Autre », qui ne dirait rien
 * du tout.
 */

const LABELS: Record<string, string> = {
  searchJiraIssuesUsingJql: "Recherche Jira",
  getJiraIssue: "Ticket Jira",
  getVisibleJiraProjects: "Projets Jira",
  getTransitionsForJiraIssue: "Transitions du ticket",
  getJiraIssueRemoteIssueLinks: "Liens du ticket",
  searchConfluenceUsingCql: "Recherche Confluence",
  getConfluencePage: "Page Confluence",
  getConfluenceSpaces: "Espaces Confluence",
  getPagesInConfluenceSpace: "Pages de l’espace",
  getConfluencePageDescendants: "Sous-pages Confluence",
  extractFigmaProcess: "Processus Figma",
  atlassianUserInfo: "Compte Atlassian",
  getAccessibleAtlassianResources: "Sites Atlassian",
};

export function labelForTool(toolName: string): string {
  return LABELS[toolName] ?? toolName;
}
