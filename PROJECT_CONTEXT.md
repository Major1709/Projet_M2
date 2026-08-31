# Contexte de référence du projet

## Vision

Créer une plateforme web de type chat donnant accès à un assistant IA capable d'exploiter les connaissances projet réparties entre Jira, Confluence et Figma.

Le LLM est servi par Groq. Il accède à Jira, Confluence et Figma au travers de serveurs MCP. Le backend de la plateforme orchestre les appels MCP, applique les règles de sécurité et gère les validations humaines.

## Principes non négociables

- Chaque utilisateur conserve les rôles et permissions de ses comptes Jira, Confluence et Figma.
- Un utilisateur ne doit jamais voir ou modifier une ressource à laquelle il n'a pas accès dans le système source.
- Le LLM ne décide jamais lui-même des permissions.
- Toute création, modification ou suppression exige une confirmation explicite de l'utilisateur.
- Avant confirmation, le chat affiche le contenu exact de l'action proposée ; pour une modification, il affiche le diff ; pour une suppression, il identifie clairement la cible.
- Les permissions sont vérifiées à nouveau juste avant l'exécution d'une action approuvée.
- Toutes les actions et validations sont journalisées.
- Jira, Confluence et Figma restent les sources de vérité. Le RAG est un index dérivé, pas une source officielle.

## Responsabilité des systèmes

### Jira

- Réception et consultation des demandes.
- Recherche, interrogation et rapprochement des tickets.
- Analyse du projet et détection de tickets proches ou dupliqués.
- Backlog opérationnel final.
- Création, modification et suppression des tickets via Jira MCP, après approbation pour toute mutation.

### Confluence

- Cahier des charges et documentation fonctionnelle.
- Lieu de création initiale des Epics et User Stories.
- Relecture, enrichissement et validation des Epics et User Stories avant leur copie vers Jira.
- Création, modification et suppression via Confluence MCP, après approbation pour toute mutation.

### Figma

- Modélisation des processus et des CJM (Customer Journey Maps).
- Consultation, création, modification et suppression des processus via Figma MCP, selon les outils réellement exposés par ce MCP.
- Mise en relation des étapes du parcours avec les exigences, Epics, User Stories et tickets.

### Knowledge/RAG

- Indexation sémantique des descriptions et métadonnées de tickets.
- Indexation des contenus Confluence autorisés et des représentations textuelles utiles provenant de Figma.
- Recherche de similarités, rapprochement des tickets, détection de doublons et analyse de couverture.
- Possibilité d'exposer ces fonctions au LLM au travers d'un Knowledge MCP interne.

## Workflow métier principal

1. Les demandes présentes dans Jira sont listées via Jira MCP, selon les droits de l'utilisateur.
2. L'utilisateur sélectionne les demandes à exploiter en cliquant sur un bouton de la plateforme.
3. La plateforme indexe les données sélectionnées dans le RAG.
4. L'assistant analyse les demandes Jira, le cahier des charges Confluence et les processus/CJM Figma.
5. L'assistant prépare les Epics, User Stories et critères d'acceptation.
6. Le chat affiche exactement ce qui sera créé dans Confluence et demande une confirmation.
7. Après confirmation et contrôle des permissions, les Epics et User Stories sont créés dans Confluence via MCP.
8. Les utilisateurs relisent, modifient et valident ces éléments dans Confluence.
9. L'assistant prépare leur copie vers le backlog Jira, détecte les doublons et présente le projet cible, les types, priorités, relations et contenus.
10. Après une nouvelle confirmation et un nouveau contrôle des permissions, les éléments validés sont créés dans Jira via MCP.
11. La plateforme conserve la liaison et l'état de synchronisation entre l'élément Confluence et le ticket Jira.

## Cycle de vie des Epics et User Stories

```text
DRAFT -> IN_REVIEW -> APPROVED -> SYNCED_TO_JIRA
                                      |
                                      +-> OUT_OF_SYNC
```

Une Epic ou User Story est un concept métier unique pouvant avoir plusieurs représentations :

```text
Epic/UserStory interne
    |-- DEFINED_IN -> contenu Confluence
    +-- COPIED_TO  -> ticket Jira
```

La liaison de synchronisation conserve au minimum la clé Jira, l'identifiant Confluence, les versions, la date, l'auteur de la validation et un hash du contenu copié.

## Politique des outils MCP

### Lecture

Les outils de recherche, consultation et listing peuvent être exécutés directement si l'utilisateur possède les droits nécessaires.

### Mutation

```text
Appel d'outil proposé par le LLM
        -> interception par le backend
        -> enregistrement PENDING_APPROVAL
        -> présentation dans le chat
        -> approbation, modification ou rejet
        -> nouvelle vérification des permissions
        -> exécution MCP avec clé d'idempotence
        -> audit du résultat
```

Le backend, et non le prompt seul, doit empêcher l'exécution immédiate des outils MCP de création, modification ou suppression.

## Modèle de connaissances envisagé

Le choix recommandé est un RAG hybride : recherche vectorielle pour la proximité sémantique et graphe métier pour les relations et la traçabilité.

Entités principales :

- Project, Request, Requirement
- CJM, JourneyStep
- Epic, UserStory, AcceptanceCriterion
- JiraIssue, ConfluencePage, FigmaFile, FigmaNode
- TextChunk et SourceVersion

Relations principales :

```text
Project HAS_REQUEST Request
Request GENERATES Requirement
CJM CONTAINS JourneyStep
JourneyStep REVEALS Requirement
Requirement COVERED_BY Epic/UserStory
Epic CONTAINS UserStory
UserStory HAS_CRITERION AcceptanceCriterion
Epic/UserStory DEFINED_IN ConfluencePage
Epic/UserStory COPIED_TO JiraIssue
UserStory DEPENDS_ON UserStory
JiraIssue SIMILAR_TO JiraIssue
```

Les relations issues directement des systèmes sources sont déterministes. Une relation inférée par l'IA conserve son origine, son score de confiance et son état de validation.

## Architecture technique envisagée

Décisions établies :

- Groq pour le LLM.
- Jira MCP, Confluence MCP et Figma MCP pour l'accès aux outils externes.
- Plateforme web conversationnelle.
- RAG sémantique et évolution possible vers un graphe de connaissances.
- Approbation humaine systématique avant toute mutation.

Stack actuellement recommandée, mais encore modifiable :

- Next.js, React et TypeScript pour le frontend.
- FastAPI, Python et Pydantic pour le backend/orchestrateur MCP.
- LangGraph pour les workflows persistants et les pauses d'approbation.
- PostgreSQL et pgvector pour les données transactionnelles et le RAG du MVP.
- Neo4j en phase ultérieure si les requêtes multi-relations le justifient.
- Celery et Redis pour l'indexation et les tâches asynchrones.
- Stockage S3/MinIO pour les instantanés bruts si nécessaire.
- OAuth/OIDC avec identité utilisateur propagée vers les serveurs MCP.
- Docker Compose pour le développement et le premier déploiement.

## Points restant à préciser

- Jira et Confluence Cloud ou Data Center.
- Serveurs MCP exacts retenus et outils qu'ils exposent réellement.
- Capacité réelle du Figma MCP à écrire et supprimer des nœuds/processus.
- Mode d'authentification de chaque MCP : jeton individuel, délégation ou compte de service.
- Modèle d'embeddings multilingue et stratégie de reranking.
- Règles de synchronisation après modification d'un élément déjà copié dans Jira.
- Volumétrie attendue, exigences d'hébergement et contraintes de confidentialité.

## Équipe d'agents retenue

Le projet est organisé autour de huit rôles :

1. Architecte / Tech Lead et coordinateur.
2. Product / Business Analyst.
3. Frontend / UX.
4. Backend.
5. IA / RAG / Knowledge Graph.
6. MCP / IAM / Sécurité.
7. QA / Test Automation.
8. DevOps / SRE.

L'environnement autorise quatre exécutions simultanées, agent principal inclus. L'architecte active dynamiquement jusqu'à trois spécialistes lorsque leurs périmètres sont indépendants. Le contrat opérationnel réutilisable de l'équipe figure dans `AGENTS.md` ; le modèle initial du Sprint 0 reste archivé dans `docs/architecture/agent-operating-model.md`.

## État du projet après le Sprint 0

- Spécification MVP, architecture, conception RAG et politique MCP/sécurité documentées.
- Scaffolds frontend et backend créés.
- Infrastructure Compose et stratégie QA créées.
- Revue sécurité du backend effectuée.
- Projet prêt à commencer un parcours vertical Jira en lecture seule.
- Mutations MCP interdites tant que les contrôles bloquants du rapport d'intégration ne sont pas réalisés.

Le rapport de référence est `docs/architecture/sprint-0-integration-report.md`.

## Organisation actuelle du code

Le frontend précédent a été retiré du dépôt le 30 août 2026 puis reconstruit
depuis une base propre dans `frontend/`. L'application Next.js implémente le
parcours conversationnel NEXIA défini par les maquettes `Screen - Chat` et
`Begin Chat`, tout en conservant les contrats et invariants de sécurité du
projet.

Le backend reste un monolithe modulaire structuré par domaines (`approvals`,
`conversations`, `agent`, `mcp`, `knowledge`, `audit`) ; chaque domaine sépare
modèles, ports, workflows et adaptateurs.

Les règles détaillées et la procédure d'ajout d'une intégration sont conservées dans `docs/architecture/code-organization.md`.
