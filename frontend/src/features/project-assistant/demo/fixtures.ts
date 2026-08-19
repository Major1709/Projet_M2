import type {
  ActionProposal,
  ChatMessage,
  ConnectorSummary,
  JiraRequest,
  UserSession,
} from "@/features/project-assistant/domain/models";

/**
 * DEMO DATA ONLY.
 * These fixtures deliberately contain no real Jira, Confluence or Figma data.
 */
export const demoSession: UserSession = {
  name: "Nora Benali",
  initials: "NB",
  role: "Product owner",
  workspace: "Portail Client",
};

export const demoConnectors: ConnectorSummary[] = [
  { system: "jira", label: "Jira", state: "connected", detail: "Accès projet vérifié" },
  {
    system: "confluence",
    label: "Confluence",
    state: "connected",
    detail: "Espace Produit connecté",
  },
  { system: "figma", label: "Figma", state: "attention", detail: "Lecture seule simulée" },
];

export const demoRequests: JiraRequest[] = [
  {
    id: "request-482",
    key: "PORTAL-482",
    title: "Simplifier la récupération de mot de passe",
    status: "En analyse",
    type: "Amélioration",
    priority: "Haute",
    updatedAt: "Il y a 12 min",
    indexation: "INDEXED",
  },
  {
    id: "request-479",
    key: "PORTAL-479",
    title: "Ajouter un suivi des demandes en temps réel",
    status: "À qualifier",
    type: "Demande",
    priority: "Moyenne",
    updatedAt: "Il y a 1 h",
    indexation: "NOT_INDEXED",
  },
  {
    id: "request-471",
    key: "PORTAL-471",
    title: "Clarifier les messages d’erreur de connexion",
    status: "Prête",
    type: "Incident",
    priority: "Haute",
    updatedAt: "Hier",
    indexation: "NOT_INDEXED",
  },
  {
    id: "request-468",
    key: "PORTAL-468",
    title: "Centraliser les préférences de notification",
    status: "Bloquée",
    type: "Demande",
    priority: "Basse",
    updatedAt: "Il y a 2 j",
    indexation: "INDEXED",
  },
];

const jiraSource = {
  id: "source-jira-482",
  system: "jira" as const,
  label: "PORTAL-482",
  title: "Simplifier la récupération de mot de passe",
  location: "Description · v7",
};

const confluenceSource = {
  id: "source-conf-auth",
  system: "confluence" as const,
  label: "Cahier des charges",
  title: "Parcours d’authentification client",
  location: "Section 4.2 · v12",
};

const figmaSource = {
  id: "source-figma-reset",
  system: "figma" as const,
  label: "CJM Authentification",
  title: "Étape « Mot de passe oublié »",
  location: "Frame 38:124",
  inferred: true,
  confidence: 0.86,
};

export const demoMessages: ChatMessage[] = [
  {
    id: "message-1",
    role: "system",
    author: "NEXIA",
    content:
      "Les réponses utilisent uniquement les sources autorisées dans votre session. Toute écriture externe attendra votre approbation.",
    createdAt: "09:38",
    status: "complete",
  },
  {
    id: "message-2",
    role: "user",
    author: "Vous",
    content:
      "Analyse PORTAL-482 et rapproche la demande du cahier des charges et du parcours client.",
    createdAt: "09:41",
    status: "complete",
  },
  {
    id: "message-3",
    role: "assistant",
    author: "NEXIA",
    content:
      "La demande vise à réduire l’abandon pendant la récupération de compte. Le cahier des charges exige un lien valable 20 minutes, tandis que le CJM signale une rupture lorsque l’utilisateur quitte l’application pour consulter son e-mail. Je propose de compléter la User Story avec une reprise de parcours et un message indiquant la durée de validité. Un ticket proche existe peut-être, mais la similarité doit encore être confirmée par un humain.",
    createdAt: "09:42",
    status: "complete",
    sources: [jiraSource, confluenceSource, figmaSource],
  },
];

export const demoActionProposal: ActionProposal = {
  id: "action-73c9",
  correlationId: "corr-demo-2026-0042",
  kind: "UPDATE",
  title: "Enrichir la User Story de récupération de compte",
  summary:
    "Cette modification complète la User Story Confluence avant sa validation et sa copie ultérieure vers Jira.",
  target: {
    system: "confluence",
    entityType: "User Story",
    externalId: "CONF-US-128",
    title: "Récupérer l’accès à mon compte",
    destination: "Espace Produit · Epic « Authentification »",
  },
  fields: [
    { label: "État après action", value: "IN_REVIEW" },
    { label: "Responsable", value: "Équipe Expérience Client" },
    {
      label: "Critères d’acceptation",
      value: [
        "Le lien de récupération expire après 20 minutes.",
        "La durée restante est indiquée avant l’envoi.",
        "Le parcours reprend après le retour depuis l’application e-mail.",
      ],
    },
  ],
  diff: [
    {
      field: "Description",
      before: "En tant que client, je veux recevoir un lien pour réinitialiser mon mot de passe.",
      after:
        "En tant que client, je veux recevoir un lien temporaire et reprendre mon parcours afin de récupérer mon compte sans recommencer.",
    },
    {
      field: "Critères d’acceptation",
      before: "Le lien permet de choisir un nouveau mot de passe.",
      after:
        "Le lien expire après 20 minutes, la durée est annoncée et le retour depuis l’e-mail reprend le parcours.",
    },
  ],
  sources: [jiraSource, confluenceSource, figmaSource],
  state: "PENDING_APPROVAL",
  version: 3,
  payloadHash: "sha256:78c4…f912",
  expiresAt: "Aujourd’hui, 17:30",
  decisionToken: "demo-decision-token-not-for-production",
};
