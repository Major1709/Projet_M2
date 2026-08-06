# Architecture système — Sprint 0

Statut : proposition d'architecture à valider

## 1. Objectif

La plateforme fournit un chat IA multi-utilisateur qui exploite les connaissances de Jira, Confluence et Figma au travers de serveurs MCP. Elle permet la lecture des ressources autorisées et prépare des actions de mutation, mais aucune création, modification ou suppression ne peut être exécutée sans approbation humaine explicite.

Le flux métier de référence est le suivant :

```text
Demandes Jira
    -> sélection et indexation RAG
    -> analyse avec Confluence et Figma
    -> préparation des Epics/User Stories
    -> approbation
    -> création initiale dans Confluence
    -> validation fonctionnelle
    -> préparation du backlog
    -> approbation
    -> copie dans Jira
```

## 2. Décisions établies

- Groq fournit le ou les LLM.
- Jira, Confluence et Figma sont accessibles par des outils MCP.
- Jira, Confluence et Figma restent les sources de vérité.
- Toute mutation nécessite une approbation explicite.
- Les permissions du système source doivent être respectées par utilisateur.
- Le RAG indexe uniquement des ressources dont la provenance et le périmètre d'accès sont connus.
- Confluence est le lieu de création initiale des Epics et User Stories ; Jira reçoit ensuite les éléments validés.

## 3. Architecture logique

```text
┌────────────────────────────────────────────────────────────┐
│ Navigateur                                                  │
│ Next.js : chat, sources, aperçu, diff, approbation          │
└───────────────────────────┬────────────────────────────────┘
                            │ HTTPS + SSE
┌───────────────────────────▼────────────────────────────────┐
│ API FastAPI                                                 │
│                                                            │
│  Identity Context ── Conversation Service ── Audit Service │
│          │                    │                    │         │
│          └──────────── Agent Orchestrator ─────────┘         │
│                               │                             │
│                     Approval Policy Engine                  │
│                               │                             │
│                         MCP Gateway                         │
└──────────────┬────────────────┼─────────────────┬───────────┘
               │                │                 │
       ┌───────▼──────┐ ┌──────▼───────┐ ┌──────▼──────┐
       │ Jira MCP     │ │Confluence MCP│ │ Figma MCP   │
       └──────────────┘ └──────────────┘ └─────────────┘
                            │
┌───────────────────────────▼────────────────────────────────┐
│ Knowledge Service                                          │
│ ingestion, recherche lexicale/vectorielle, graphe, sources │
└───────────────┬────────────────────────────┬───────────────┘
                │                            │
       ┌────────▼────────┐          ┌────────▼────────┐
       │ PostgreSQL      │          │ Workers         │
       │ pgvector        │          │ Celery + Redis  │
       └────────┬────────┘          └─────────────────┘
                │
       ┌────────▼────────┐
       │ Neo4j, phase 2  │
       └─────────────────┘
```

## 4. Modules et responsabilités

### 4.1 Frontend web

Responsabilités :

- authentifier l'utilisateur ;
- afficher et diffuser les réponses du chat ;
- afficher les sources et leur provenance ;
- présenter les actions proposées sous une forme structurée ;
- afficher un diff avant modification ;
- exiger une confirmation explicite ;
- suivre l'état d'une importation ou d'une synchronisation ;
- ne jamais considérer un contrôle d'interface comme un contrôle d'autorisation suffisant.

### 4.2 API et services métier

Le backend est un monolithe modulaire pour le MVP. Les modules prévus sont :

```text
identity       identité interne et connexions externes
conversations conversations, messages et sources citées
projects       configuration des projets et espaces connectés
approvals      actions proposées et décisions humaines
orchestration  états et reprise des workflows IA
mcp_gateway    catalogue, politique et exécution des outils MCP
knowledge      ingestion, chunks, embeddings et recherche
sync           liens Confluence/Jira et détection OUT_OF_SYNC
audit          événements de sécurité et d'activité
```

Ces modules partagent PostgreSQL dans le MVP, mais ne doivent pas écrire directement dans les tables des autres modules.

### 4.3 Agent Orchestrator

L'orchestrateur :

- sélectionne le prompt et le profil Groq approprié ;
- fournit uniquement les outils autorisés pour le contexte courant ;
- conserve l'état du workflow ;
- transforme un appel d'outil de mutation en proposition persistée ;
- reprend le workflow après approbation, modification ou rejet ;
- borne le nombre d'étapes et d'appels afin d'éviter les boucles et les coûts incontrôlés.

Le fournisseur LLM est placé derrière une interface `LLMProvider` afin de ne pas coupler le domaine au SDK Groq.

### 4.4 Approval Policy Engine

Le moteur de politique classe les outils MCP :

```text
READ          exécution possible après contrôle des droits
CREATE        approbation obligatoire
UPDATE        diff et approbation obligatoires
DELETE        confirmation renforcée obligatoire
SYNC          aperçu complet et approbation obligatoire
ADMIN         interdit par défaut
```

Une approbation porte sur un instantané immuable des arguments. Si les arguments, la cible ou les permissions changent, l'approbation est invalidée.

### 4.5 MCP Gateway

Le gateway est le seul module autorisé à communiquer avec les serveurs MCP externes. Il :

- découvre et versionne le catalogue des outils ;
- applique une allowlist par environnement et par rôle applicatif ;
- associe chaque appel à l'utilisateur, la conversation et l'approbation éventuelle ;
- impose délais, quotas, taille maximale et validation de schéma ;
- masque les secrets dans les journaux ;
- produit un événement d'audit avant et après exécution ;
- revalide les droits auprès de la source avant une mutation ;
- utilise des clés d'idempotence pour les créations et synchronisations.

Le LLM ne possède pas les jetons et ne choisit jamais l'identité d'exécution.

### 4.6 Knowledge Service

Le service de connaissances sépare :

- les artefacts sources et leurs versions ;
- les fragments textuels indexables ;
- les embeddings ;
- les entités métier ;
- les relations déterministes ou inférées ;
- les informations de provenance et de périmètre d'accès.

Une réponse RAG est constituée uniquement après filtrage par utilisateur, tenant, projet, espace et ressource. Les identifiants des sources utilisées sont enregistrés avec le message généré.

## 5. Flux de lecture

```text
1. Le frontend envoie la question avec l'identité de session.
2. Le backend dérive le contexte d'autorisation côté serveur.
3. L'orchestrateur choisit les outils de lecture disponibles.
4. Le Knowledge Service filtre puis recherche les sources autorisées.
5. Si nécessaire, le MCP Gateway consulte une source en temps réel.
6. Groq reçoit seulement le contexte minimal nécessaire.
7. La réponse est diffusée avec ses citations.
8. La conversation et les références de provenance sont persistées.
```

## 6. Flux de mutation

```text
1. Groq propose un appel d'outil et des arguments structurés.
2. Le backend valide le schéma, la cible et la classification de l'outil.
3. Le backend crée une ActionProposal immuable.
4. Le frontend affiche la cible, le contenu et le diff éventuel.
5. L'utilisateur approuve, modifie ou rejette.
6. Toute modification crée une nouvelle proposition à approuver.
7. Après approbation, les permissions sont vérifiées de nouveau.
8. Le MCP Gateway exécute l'appel avec l'identité autorisée.
9. Le résultat, l'erreur et les identifiants externes sont audités.
10. Le workflow reprend et présente le résultat à l'utilisateur.
```

États proposés :

```text
DRAFT -> PENDING_APPROVAL -> APPROVED -> EXECUTING -> SUCCEEDED
             |                  |            |
             +-> REJECTED       |            +-> FAILED
             +-> SUPERSEDED     +-> EXPIRED
```

## 7. Données transactionnelles minimales

```text
User
ExternalIdentity
ProjectConnection
Conversation
Message
MessageCitation
WorkflowRun
ActionProposal
ApprovalDecision
ToolExecution
AuditEvent
SourceArtifact
SourceVersion
TextChunk
Embedding
KnowledgeEntity
KnowledgeRelation
ConfluenceJiraLink
IngestionJob
```

Toutes les tables métier importantes portent un `tenant_id`. Les ressources indexées portent aussi leur système source, identifiant externe, version, projet/espace, URL et informations de provenance.

## 8. API applicative indicative

```text
POST   /api/conversations
POST   /api/conversations/{id}/messages
GET    /api/conversations/{id}/events

POST   /api/ingestions/jira-selection
GET    /api/ingestions/{id}

GET    /api/actions/{id}
POST   /api/actions/{id}/approve
POST   /api/actions/{id}/reject
POST   /api/actions/{id}/revise

GET    /api/source-artifacts/{id}
GET    /api/sync/confluence-jira
```

Les commandes d'approbation exigent un jeton anti-rejeu et une version attendue de la proposition.

## 9. Déploiement MVP

Conteneurs proposés :

```text
frontend
api
worker
postgres-pgvector
redis
```

Les serveurs MCP peuvent être distants ou déployés séparément. Ils ne partagent pas leurs secrets avec le frontend. Neo4j et MinIO sont ajoutés seulement si les besoins validés le justifient.

## 10. Structure cible du dépôt

```text
frontend/
  src/
    app/
    features/
backend/
  app/
    core/
    conversations/
    approvals/
    agent/
    mcp/
    knowledge/
    audit/
    bootstrap.py
  tests/
infra/
docs/
  architecture/
  product/
  security/
  qa/
```

Les responsabilités internes et les règles de dépendance sont détaillées dans `docs/architecture/code-organization.md`.

## 11. Exigences transversales

- Chaque réponse factuelle doit pouvoir exposer ses sources.
- Les appels MCP doivent être traçables sans journaliser les secrets.
- Les opérations de mutation doivent être idempotentes ou détecter les répétitions.
- Les traitements asynchrones doivent être reprenables.
- Les suppressions logiques internes sont préférées quand elles sont possibles.
- Les erreurs externes ne doivent pas produire une confirmation trompeuse de réussite.
- Le RAG doit être évalué sur la pertinence, la fidélité aux sources et l'absence de fuite d'autorisation.
- Les prompts et modèles doivent être versionnés avec chaque exécution importante.

## 12. Questions bloquantes avant la production

- Jira et Confluence sont-ils Cloud ou Data Center ?
- Quels serveurs MCP précis seront utilisés et quelles mutations exposent-ils ?
- Comment chaque MCP représente-t-il l'identité de l'utilisateur final ?
- Le Figma MCP peut-il réellement créer, modifier et supprimer les éléments CJM nécessaires ?
- Où les données et embeddings doivent-ils être hébergés ?
- Quels volumes, objectifs de latence et durées de conservation sont attendus ?
- Quelle règle métier s'applique lorsqu'une Story Confluence déjà copiée est modifiée ?

## 13. Séquencement recommandé

1. Valider les cas d'usage et les contrats d'approbation.
2. Qualifier les trois MCP et leur modèle d'identité.
3. Construire le squelette frontend/backend et l'audit.
4. Implémenter un parcours vertical en lecture sur Jira.
5. Ajouter l'indexation et la recherche avec permissions.
6. Implémenter une création Confluence avec approbation.
7. Implémenter la copie Confluence vers Jira avec idempotence.
8. Ajouter Figma/CJM après validation des capacités d'écriture.
9. Mesurer la qualité du RAG avant d'introduire Neo4j.
