# Spécification produit du MVP

## 1. Statut du document

Ce document formalise le cadrage produit du MVP à partir du contexte de référence du projet. Il distingue explicitement :

- les décisions déjà établies ;
- les hypothèses de travail nécessaires au cadrage ;
- les choix qui restent à décider ou à valider techniquement.

Il ne remplace pas les permissions, les workflows ni les données configurés dans Jira, Confluence et Figma.

## 2. Vision produit

Fournir une plateforme web conversationnelle dans laquelle un utilisateur peut exploiter, relier et transformer les connaissances projet réparties entre Jira, Confluence et Figma, sans contourner les permissions des systèmes sources.

L'assistant, servi par un LLM Groq et connecté aux trois outils par MCP, doit aider l'utilisateur à :

- comprendre et rapprocher des demandes Jira ;
- enrichir cette analyse avec le cahier des charges Confluence et les processus/CJM Figma ;
- préparer les Epics et User Stories dans Confluence, où elles sont relues et validées ;
- copier ensuite les éléments validés dans le backlog Jira ;
- consulter et, si le MCP le permet, gérer des processus/CJM Figma ;
- préparer toute mutation, en montrer le contenu exact et attendre une autorisation humaine explicite avant de l'exécuter.

La promesse produit n'est donc pas « une IA qui agit seule », mais « un assistant traçable qui prépare des décisions et exécute uniquement les actions validées dans les limites des droits de l'utilisateur ».

## 3. Principes produit non négociables

1. Jira, Confluence et Figma restent les sources de vérité. Le RAG est un index dérivé et reconstructible.
2. L'utilisateur ne consulte et ne manipule que les ressources auxquelles son compte a accès dans le système source.
3. Le LLM ne prend aucune décision d'autorisation.
4. Toute création, modification ou suppression exige une confirmation explicite avant exécution.
5. Le contenu approuvé doit être identique au contenu exécuté. Toute modification après approbation déclenche une nouvelle approbation.
6. Les permissions sont contrôlées de nouveau juste avant la mutation.
7. Toute proposition, décision humaine, tentative d'exécution et résultat sont auditables.
8. Les Epics et User Stories sont créées initialement dans Confluence, puis copiées dans Jira uniquement après validation.
9. Les réponses issues du RAG doivent conserver leur provenance et ne jamais exposer un contenu devenu inaccessible.

## 4. Acteurs

### 4.1 Acteurs humains

| Acteur | Objectif | Autorité dans le MVP |
|---|---|---|
| Utilisateur projet authentifié | Rechercher, analyser, générer des propositions et demander des actions | Limitée aux droits de ses comptes Jira, Confluence et Figma |
| Rédacteur fonctionnel | Relire et enrichir les Epics/User Stories dans Confluence | Déterminée par les permissions Confluence ; l'existence d'un rôle applicatif distinct reste à décider |
| Validateur fonctionnel | Déclarer les Epics/User Stories prêtes à être copiées vers Jira | Règle de désignation et traduction en permissions à décider |
| Administrateur de la plateforme | Exploiter la plateforme, ses configurations et ses journaux techniques | Ne reçoit pas automatiquement un droit de lecture sur les contenus métier externes |
| Auditeur autorisé | Examiner les décisions et actions enregistrées | Périmètre et durée d'accès à décider |

Une même personne peut cumuler plusieurs fonctions. Le MVP ne doit pas inventer de nouveaux droits métier qui élargiraient ceux des systèmes sources.

### 4.2 Acteurs systèmes

| Acteur système | Responsabilité |
|---|---|
| Interface de chat web | Recevoir les demandes, afficher les sources, les propositions, les diffs et les demandes d'approbation |
| Backend/orchestrateur | Gérer le contexte utilisateur, les workflows, les appels MCP, les approbations, l'idempotence et l'audit |
| LLM Groq | Comprendre les intentions, synthétiser les connaissances et produire des réponses/propositions structurées |
| Jira MCP | Lire et muter Jira dans les limites des outils exposés et des droits de l'utilisateur |
| Confluence MCP | Lire et muter Confluence dans les limites des outils exposés et des droits de l'utilisateur |
| Figma MCP | Lire et, si possible, muter les processus/CJM dans les limites des outils exposés et des droits de l'utilisateur |
| Knowledge/RAG | Indexer les sources autorisées, rechercher des similarités et fournir des résultats avec provenance |

## 5. Périmètre du MVP

### 5.1 Inclus

- Authentification d'un utilisateur et association de son identité aux connexions MCP nécessaires.
- Chat web avec réponses accompagnées de références vers les sources utilisées.
- Listing des demandes Jira accessibles à l'utilisateur.
- Sélection explicite de demandes Jira à indexer.
- Indexation des descriptions et métadonnées utiles dans un RAG sémantique.
- Recherche sémantique et textuelle, rapprochement de tickets et signalement de doublons potentiels.
- Consultation de contenus Confluence et de représentations textuelles utiles des processus/CJM Figma accessibles.
- Génération structurée d'Epics, User Stories et critères d'acceptation à partir des connaissances autorisées.
- Prévisualisation, approbation puis création initiale des Epics/User Stories dans Confluence.
- Représentation du cycle `DRAFT -> IN_REVIEW -> APPROVED -> SYNCED_TO_JIRA`, avec détection de l'état `OUT_OF_SYNC`.
- Préparation et prévisualisation de la copie des éléments Confluence validés vers le backlog Jira.
- Détection de doublons avant la copie, puis confirmation et création dans Jira.
- Conservation de la liaison Confluence–Jira et des versions/hash utilisés lors de la copie.
- Recherche, consultation, création, modification et suppression de tickets Jira, sous réserve des droits et des outils Jira MCP.
- Création, modification et suppression de contenus Confluence, sous réserve des droits et des outils Confluence MCP.
- Consultation des processus/CJM Figma et rattachement de leurs étapes aux exigences, Epics, User Stories ou tickets.
- Préparation de créations, modifications et suppressions de processus/CJM Figma. Leur exécution dans le MVP est conditionnée par les capacités d'écriture réelles du Figma MCP, encore à valider.
- Approbation obligatoire et audit pour toutes les mutations.

### 5.2 Hors périmètre du MVP

- Exécution autonome d'une mutation sans validation humaine.
- Remplacement de Jira, Confluence ou Figma comme source de vérité.
- Synchronisation bidirectionnelle automatique et continue entre Confluence et Jira.
- Résolution automatique des conflits entre une version Confluence et une version Jira.
- Modification automatique d'un backlog entier sur la seule base d'une réponse conversationnelle.
- Graphe de connaissances spécialisé dans une base dédiée telle que Neo4j ; le MVP peut conserver des relations métier dans son stockage principal. Le passage à un GraphRAG complet est une évolution.
- Extraction automatique non supervisée de toutes les relations métier avec valeur de vérité.
- Administration des permissions Jira, Confluence ou Figma depuis la plateforme.
- Entraînement ou fine-tuning d'un modèle propriétaire.
- Application mobile native.
- Couverture d'outils projet autres que Jira, Confluence et Figma.

## 6. Parcours métier principal

### 6.1 De la demande Jira à la conception dans Confluence

1. L'utilisateur ouvre la plateforme et s'authentifie.
2. La plateforme liste, via Jira MCP, uniquement les demandes Jira accessibles.
3. L'utilisateur sélectionne une ou plusieurs demandes et déclenche explicitement leur indexation.
4. Le backend vérifie l'accès, récupère les données sélectionnées et les indexe dans le RAG avec leur provenance, leur version et leur périmètre d'accès.
5. L'utilisateur demande une analyse, un rapprochement ou la génération d'un backlog fonctionnel.
6. L'assistant consulte les sources Jira, Confluence et Figma nécessaires et autorisées, puis recherche les contenus similaires dans le RAG.
7. Il produit un ensemble structuré d'Epics, User Stories, critères d'acceptation, relations et alertes de doublon, avec références aux sources.
8. Le chat affiche le contenu exact qui serait créé dans Confluence.
9. L'utilisateur approuve, demande une modification ou rejette la proposition.
10. En cas d'approbation, le backend recontrôle les permissions puis crée les éléments dans Confluence via MCP avec une clé d'idempotence.

### 6.2 De Confluence au backlog Jira

1. Les utilisateurs relisent et enrichissent les éléments dans Confluence.
2. Un acteur autorisé les fait passer à l'état `APPROVED`. Le mécanisme concret de validation Confluence reste à décider.
3. L'assistant récupère la version approuvée et compare son hash à la dernière version connue.
4. Il prépare le mapping vers Jira : projet cible, type de ticket, titre, description, critères d'acceptation, priorité, labels et relations.
5. Il recherche les tickets proches ou déjà liés et signale les doublons potentiels.
6. Le chat affiche l'ensemble exact des tickets à créer et les avertissements détectés.
7. L'utilisateur autorisé approuve, modifie ou rejette la copie.
8. Après un nouveau contrôle des permissions, le backend crée les tickets via Jira MCP de manière idempotente.
9. La plateforme enregistre la clé Jira, l'identifiant Confluence, les versions, le hash du contenu, la date, l'auteur de l'approbation et le résultat d'exécution.
10. Si le contenu Confluence change ensuite, la plateforme marque la liaison `OUT_OF_SYNC`. Le comportement après ce signalement reste à décider.

### 6.3 Gestion Figma/CJM via MCP

1. L'utilisateur demande à consulter ou exploiter un processus/CJM Figma.
2. Le backend utilise le Figma MCP dans le contexte des droits de l'utilisateur.
3. L'assistant peut utiliser une représentation textuelle du CJM comme contexte et relier les étapes du parcours aux exigences et artefacts projet.
4. Pour une création, modification ou suppression, l'assistant prépare une proposition structurée et le chat montre la cible ainsi que le contenu exact ou le diff.
5. L'exécution attend une approbation explicite, puis un nouveau contrôle des permissions.
6. Le Figma MCP exécute la mutation seulement si l'outil correspondant existe réellement. À défaut, la plateforme doit expliquer que l'action ne peut pas être exécutée ; la solution de remplacement reste à décider.

## 7. Catalogue des cas d'usage

| ID | Cas d'usage | Acteur principal | Système(s) | Mutation / approbation |
|---|---|---|---|---|
| UC-01 | Lister les demandes Jira accessibles | Utilisateur projet | Jira MCP | Non |
| UC-02 | Indexer une sélection de demandes | Utilisateur projet | Jira MCP, RAG | Écriture interne déclenchée explicitement ; pas de mutation source |
| UC-03 | Interroger et résumer un projet | Utilisateur projet | RAG, Jira, Confluence, Figma MCP | Non |
| UC-04 | Rechercher un ticket par texte ou sens | Utilisateur projet | Jira MCP, RAG | Non |
| UC-05 | Rapprocher des tickets et détecter des doublons potentiels | Utilisateur projet | RAG, Jira MCP | Non |
| UC-06 | Analyser la couverture demande–exigence–CJM–story | Utilisateur projet | RAG et trois MCP | Non |
| UC-07 | Générer des Epics/User Stories et critères d'acceptation | Utilisateur projet | LLM, RAG | Proposition seulement |
| UC-08 | Créer les Epics/User Stories dans Confluence | Rédacteur autorisé | Confluence MCP | Oui, obligatoire |
| UC-09 | Modifier ou supprimer un contenu Confluence | Rédacteur autorisé | Confluence MCP | Oui, diff/cible et approbation |
| UC-10 | Valider une Epic/User Story dans Confluence | Validateur fonctionnel | Confluence MCP | Oui si la validation modifie la source ; mécanisme à décider |
| UC-11 | Préparer le backlog Jira depuis les éléments validés | Utilisateur projet | Confluence, Jira MCP, RAG | Proposition seulement |
| UC-12 | Copier les Epics/User Stories validées dans Jira | Utilisateur autorisé | Jira MCP | Oui, obligatoire |
| UC-13 | Créer, modifier ou supprimer un ticket Jira | Utilisateur autorisé | Jira MCP | Oui, obligatoire |
| UC-14 | Consulter un processus/CJM | Utilisateur projet | Figma MCP | Non |
| UC-15 | Créer, modifier ou supprimer un processus/CJM | Utilisateur autorisé | Figma MCP | Oui, obligatoire ; capacité MCP à valider |
| UC-16 | Identifier les éléments Confluence désynchronisés de Jira | Utilisateur projet | Stockage de liaison, Confluence, Jira MCP | Non |
| UC-17 | Consulter l'historique d'une action | Auditeur autorisé | Journal d'audit | Non |

## 8. User Stories priorisées

La priorité `P0` désigne un besoin indispensable au parcours de valeur du MVP. `P1` désigne un besoin important pouvant être livré après le premier parcours complet. `P2` désigne une amélioration ultérieure.

### US-01 — Accéder avec les permissions réelles (`P0`)

**En tant qu'** utilisateur projet, **je veux** utiliser la plateforme avec mon identité et mes permissions externes **afin de** ne voir et manipuler que les données auxquelles j'ai droit.

Critères d'acceptation :

- Étant donné un utilisateur authentifié, quand il lance une lecture Jira, Confluence ou Figma, alors l'appel est effectué dans un contexte d'identité traçable.
- Étant donné une ressource interdite dans le système source, quand l'utilisateur tente d'y accéder directement ou par le chat/RAG, alors aucun contenu de cette ressource n'est retourné.
- Étant donné une permission retirée après la préparation d'une action, quand l'utilisateur l'approuve, alors le nouveau contrôle refuse l'exécution et journalise le refus.

### US-02 — Sélectionner et indexer des demandes Jira (`P0`)

**En tant qu'** utilisateur projet, **je veux** lister puis sélectionner des demandes Jira **afin de** les rendre exploitables par la recherche sémantique.

Critères d'acceptation :

- La liste ne contient que des demandes accessibles à l'utilisateur et affiche au minimum leur clé, leur titre et leur statut si ces champs sont autorisés.
- L'indexation ne démarre qu'après une action explicite de sélection et de déclenchement par l'utilisateur.
- Chaque fragment indexé conserve l'identifiant source, la version, l'URL ou référence source, la date d'indexation et le périmètre nécessaire au contrôle d'accès.
- Une réindexation de la même version ne crée pas de doublon logique.

### US-03 — Poser des questions avec provenance (`P0`)

**En tant qu'** utilisateur projet, **je veux** interroger les connaissances du projet dans le chat **afin de** obtenir une réponse vérifiable.

Critères d'acceptation :

- Une réponse factuelle fondée sur les sources contient les références Jira, Confluence ou Figma utilisées.
- Si aucune source autorisée ne permet de répondre, le chat le dit explicitement au lieu de présenter une hypothèse comme un fait.
- Les résultats RAG sont filtrés selon les droits actuels de l'utilisateur avant d'être exposés au LLM et au chat.

### US-04 — Détecter les tickets similaires (`P0`)

**En tant qu'** utilisateur projet, **je veux** trouver les tickets proches d'une demande **afin de** réduire les doublons et réutiliser les connaissances existantes.

Critères d'acceptation :

- Pour une demande sélectionnée, la plateforme retourne une liste ordonnée de candidats autorisés avec leur score ou niveau de similarité et leur provenance.
- Chaque candidat est présenté comme une suggestion tant qu'aucun humain ne l'a confirmé comme doublon.
- Un ticket inaccessible ne peut apparaître ni directement, ni par son titre, ni par une explication de similarité.

### US-05 — Générer un backlog fonctionnel dans Confluence (`P0`)

**En tant que** rédacteur fonctionnel, **je veux** générer une proposition d'Epics, User Stories et critères d'acceptation **afin de** la relire avant toute création.

Critères d'acceptation :

- La proposition distingue les Epics, leurs User Stories, les critères d'acceptation et les relations proposées.
- La proposition indique les sources qui ont contribué à chaque élément ou signale l'absence de source directe.
- Aucun élément n'est écrit dans Confluence au stade de génération.
- Le chat affiche le contenu exact et la destination Confluence envisagée avant de permettre l'approbation.

### US-06 — Approuver et créer dans Confluence (`P0`)

**En tant que** rédacteur autorisé, **je veux** approuver une proposition **afin de** créer les éléments dans Confluence de façon contrôlée.

Critères d'acceptation :

- L'utilisateur peut approuver, rejeter ou demander une modification de la proposition.
- Une proposition modifiée après affichage ne peut pas réutiliser une approbation antérieure.
- Avant l'exécution, le backend recontrôle les permissions Confluence.
- Après exécution, le chat affiche le résultat et les identifiants ou liens des contenus créés.
- Une nouvelle tentative avec la même clé d'idempotence ne crée pas une seconde copie des mêmes éléments.

### US-07 — Valider le contenu fonctionnel avant Jira (`P0`)

**En tant que** validateur fonctionnel autorisé, **je veux** distinguer les éléments approuvés des brouillons **afin de** n'envoyer dans Jira que le contenu validé.

Critères d'acceptation :

- Un élément non `APPROVED` ne peut pas être inclus dans une copie vers Jira.
- La plateforme conserve l'identité du validateur, la version validée et la date.
- Si la version Confluence change après validation mais avant copie, la plateforme bloque ou redemande une validation ; la règle exacte reste à décider avant implémentation.

### US-08 — Préparer et copier le backlog vers Jira (`P0`)

**En tant qu'** utilisateur autorisé, **je veux** copier dans Jira les éléments Confluence validés **afin de** constituer le backlog opérationnel.

Critères d'acceptation :

- La préparation n'inclut que des éléments à l'état `APPROVED` et affiche le projet cible, les types, titres, descriptions, critères, priorités, labels et relations disponibles.
- La plateforme signale les doublons potentiels et les éléments déjà liés à Jira avant l'approbation.
- Aucun ticket n'est créé avant l'approbation explicite du lot ou de ses éléments, selon une granularité qui reste à décider.
- Les permissions Jira sont recontrôlées juste avant la création.
- Chaque ticket créé est lié à son élément Confluence avec les identifiants, versions, hash, date et auteur de l'approbation.
- En cas d'échec partiel, le résultat distingue sans ambiguïté les créations réussies, échouées et non tentées, sans dupliquer les réussites lors d'une reprise.

### US-09 — Contrôler toute modification ou suppression (`P0`)

**En tant qu'** utilisateur autorisé, **je veux** voir précisément l'effet d'une modification ou suppression **afin de** confirmer consciemment l'action.

Critères d'acceptation :

- Pour une modification, l'interface montre la cible et un diff entre les valeurs actuelles et proposées.
- Pour une suppression, l'interface montre au minimum le système, le type, l'identifiant et le titre de la cible.
- Les boutons d'approbation, de rejet et de demande de modification sont explicites.
- Une mutation refusée ou expirée n'est jamais transmise au MCP.
- Chaque tentative et son résultat sont inscrits dans l'audit.

### US-10 — Consulter et relier les CJM (`P1`)

**En tant qu'** utilisateur projet, **je veux** exploiter les étapes d'un CJM Figma **afin de** relier le parcours client aux exigences et au backlog.

Critères d'acceptation :

- La plateforme ne récupère que les fichiers et nœuds Figma accessibles à l'utilisateur.
- Une étape de parcours utilisée dans une analyse conserve une référence au fichier/nœud Figma source.
- Les relations inférées par l'IA sont identifiées comme telles, avec un score ou niveau de confiance, et ne deviennent pas automatiquement des vérités métier.

### US-11 — Gérer un processus/CJM via Figma MCP (`P1`, conditionnelle)

**En tant qu'** utilisateur autorisé, **je veux** créer, modifier ou supprimer un processus/CJM **afin de** maintenir le parcours depuis le chat.

Critères d'acceptation :

- Le serveur Figma MCP sélectionné expose et permet de tester l'outil de mutation correspondant ; sinon la story est bloquée et non déclarée livrée.
- Avant une création, le chat affiche la structure exacte proposée ; avant une modification, le diff ; avant une suppression, la cible exacte.
- L'action n'est transmise au Figma MCP qu'après approbation et nouveau contrôle des permissions.
- Le résultat contient une référence au fichier et aux nœuds créés ou modifiés lorsque le MCP les fournit.

### US-12 — Détecter une désynchronisation Confluence–Jira (`P1`)

**En tant qu'** utilisateur projet, **je veux** être informé lorsqu'un élément Confluence copié change **afin de** savoir que Jira ne reflète plus la version fonctionnelle.

Critères d'acceptation :

- La plateforme compare la version ou le hash courant Confluence à celui copié vers Jira.
- En cas de différence, la liaison passe à `OUT_OF_SYNC` sans modifier automatiquement Jira.
- Le chat peut expliquer quels champs ont changé si les versions nécessaires sont accessibles.

### US-13 — Auditer les décisions et actions (`P0`)

**En tant qu'** auditeur autorisé, **je veux** retracer une mutation **afin de** vérifier qui a proposé, approuvé et exécuté quoi.

Critères d'acceptation :

- L'audit conserve l'utilisateur, la date, le système cible, l'outil MCP, la cible, le payload ou hash du payload, la décision humaine et le résultat.
- Une corrélation permet de suivre la proposition depuis le chat jusqu'à l'exécution MCP.
- Les secrets et jetons d'accès ne sont jamais stockés en clair dans le journal.
- Les droits d'accès au journal sont contrôlés et ne donnent pas indirectement accès à un contenu source interdit.

### US-14 — Rechercher par relations métier (`P2`)

**En tant qu'** utilisateur projet, **je veux** naviguer de la demande à l'exigence, au CJM, à l'Epic et au ticket Jira **afin de** comprendre la couverture et l'impact.

Critères d'acceptation :

- Les relations déterministes provenant des systèmes sources sont distinguées des relations inférées.
- Les traversées ne retournent que des nœuds et relations autorisés.
- Le besoin d'une base graphe dédiée est évalué sur des requêtes et volumes réels avant adoption.

## 9. Règles d'approbation

### 9.1 Classification des actions

| Classe | Exemples | Politique |
|---|---|---|
| Lecture | Lister, rechercher, consulter, résumer | Exécution directe après contrôle d'accès ; pas d'approbation de mutation |
| Écriture interne dérivée | Indexer dans le RAG, enregistrer une conversation | Déclenchement utilisateur explicite pour l'indexation ; aucune écriture dans une source externe |
| Création externe | Créer une page, Epic, User Story, ticket ou CJM | Aperçu exact et approbation obligatoire |
| Modification externe | Modifier un ticket, une page ou un CJM | Diff, approbation obligatoire et recontrôle des permissions |
| Suppression externe | Supprimer un ticket, une page ou un CJM | Cible explicite, avertissement renforcé, approbation obligatoire et recontrôle des permissions |
| Copie par lot | Copier des éléments Confluence vers Jira | Aperçu complet, alertes de doublon, approbation et exécution idempotente |

### 9.2 États minimums d'une demande de mutation

```text
PROPOSED -> PENDING_APPROVAL -> APPROVED -> PERMISSION_CHECK -> EXECUTING -> COMPLETED
                              |             |                  |
                              +-> REJECTED  +-> DENIED         +-> FAILED/PARTIAL
                              |
                              +-> CHANGE_REQUESTED
```

Un état d'expiration est attendu, mais sa durée et sa politique restent à décider.

### 9.3 Invariants

- L'approbation porte sur un payload versionné ou un hash immuable.
- Une modification du payload, de la cible ou du contexte d'exécution invalide l'approbation.
- L'identité de l'approbateur est enregistrée.
- La permission du système source prévaut sur toute décision locale.
- Une approbation ne compense jamais une permission absente.
- Une clé d'idempotence protège les créations et reprises.
- Une exécution partielle ne doit pas être présentée comme un succès complet.
- La possibilité d'approuver son propre changement, la double approbation pour une suppression et la granularité d'approbation des lots restent à décider.

## 10. Exigences non fonctionnelles

### 10.1 Sécurité et confidentialité

- Appliquer le principe du moindre privilège aux utilisateurs, au backend et aux serveurs MCP.
- Ne jamais se fier au LLM pour autoriser une action.
- Filtrer les résultats avant leur transmission au LLM et avant leur affichage.
- Chiffrer les jetons et secrets au repos et en transit ; la technologie de gestion des secrets reste à choisir.
- Isoler les données indexées de façon à empêcher toute fuite inter-utilisateurs, inter-projets ou inter-espaces.
- Considérer les contenus Jira, Confluence et Figma comme non fiables vis-à-vis du prompt injection ; les instructions contenues dans les sources ne doivent pas pouvoir modifier la politique d'outils.
- Ne jamais inscrire de secret, jeton ou donnée d'authentification dans les prompts, réponses ou journaux.

### 10.2 Traçabilité et explicabilité

- Toute réponse fondée sur une source doit permettre de retrouver cette source.
- Toute relation inférée doit être distinguée d'une relation source ou validée.
- Toute mutation doit disposer d'un identifiant de corrélation de bout en bout.
- La durée de conservation et le niveau de détail des journaux restent à décider selon les contraintes réglementaires et de confidentialité.

### 10.3 Fiabilité et cohérence

- Les mutations doivent être idempotentes ou protégées contre les doublons.
- Les erreurs MCP et les échecs partiels doivent être visibles et rejouables sans répéter une action réussie.
- Le RAG doit détecter les changements de version ou permettre une réindexation contrôlée.
- L'indisponibilité d'un MCP ne doit pas être masquée par une réponse inventée du LLM.
- Les stratégies de reprise, de sauvegarde, de RPO et de RTO restent à définir.

### 10.4 Performance et capacité

- Le chat doit fournir un retour visuel immédiat lors d'un traitement long et permettre le suivi des étapes asynchrones.
- L'indexation doit pouvoir s'exécuter en arrière-plan sans bloquer la navigation.
- Les objectifs chiffrés de latence, débit, concurrence et volumétrie ne sont pas encore décidés et doivent être fixés avant le test de charge.

### 10.5 Qualité IA et RAG

- Les générations structurées doivent respecter un schéma validé par le backend avant toute présentation ou exécution.
- Une suggestion de doublon ou de relation ne doit pas être assimilée à une vérité sans validation humaine.
- Un jeu d'évaluation projet doit mesurer au minimum la pertinence de recherche, la fidélité aux sources, la qualité des Epics/User Stories et les fuites de permissions.
- Les seuils d'acceptation, le modèle Groq exact, le modèle d'embeddings et le reranker restent à choisir.

### 10.6 Accessibilité et compatibilité

- Les actions critiques doivent être compréhensibles au clavier et ne pas dépendre uniquement d'une couleur.
- Le niveau WCAG cible, les navigateurs supportés et les langues de l'interface restent à décider.

### 10.7 Exploitabilité

- Les appels LLM, RAG et MCP doivent être corrélables sans exposer de secrets.
- Des métriques doivent couvrir les erreurs, latences, refus de permission, demandes d'approbation et résultats de mutation.
- Les alertes, SLO et responsabilités d'astreinte restent hors décision à ce stade.

## 11. Hypothèses de travail

Ces hypothèses servent à rendre le MVP spécifiable ; elles doivent être confirmées avant ou pendant le Sprint 0 technique.

1. Les serveurs MCP permettent au backend d'identifier l'utilisateur à l'origine d'un appel et de préserver ses permissions, ou une couche d'autorisation équivalente sera construite.
2. Les APIs et outils MCP fournissent des identifiants stables et suffisamment de métadonnées de version pour assurer la traçabilité.
3. Jira permet de représenter les Epics, User Stories et leurs relations dans le projet cible.
4. Confluence fournit une structure identifiable pour stocker et relire les Epics/User Stories avant Jira.
5. Une représentation textuelle exploitable d'un processus/CJM peut être obtenue depuis Figma.
6. Les contenus à traiter peuvent être envoyés au service LLM Groq dans le respect des contraintes de l'organisation ; cette hypothèse doit être validée juridiquement et en sécurité.
7. Le MVP démarre avec une recherche hybride textuelle et vectorielle ; un graphe dédié n'est adopté que si des cas mesurés le justifient.
8. Le français est une langue de contenu importante. Les autres langues requises et la langue de l'interface restent à confirmer.

## 12. Questions ouvertes et décisions requises

### 12.1 Produit et gouvernance

- Qui peut valider une Epic/User Story pour le passage vers Jira ?
- Un utilisateur peut-il approuver sa propre proposition ?
- Une suppression exige-t-elle une double approbation ou une saisie de confirmation renforcée ?
- Une copie en lot est-elle approuvée globalement ou élément par élément ?
- Quel est le mécanisme officiel de statut dans Confluence : propriété de page, label, contenu structuré ou donnée interne ?
- Quelle est la structure éditoriale cible dans Confluence : une page par Epic, une page par Story, une base de données ou un gabarit spécifique ?
- Quelles règles définissent qu'un ticket est un doublon et qui peut confirmer cette qualification ?
- Quel comportement est attendu après `OUT_OF_SYNC` : simple alerte, proposition de diff, mise à jour Jira ou nouvelle copie ?
- Quelle politique de suppression s'applique aux artefacts déjà liés entre Confluence et Jira ?

### 12.2 Intégrations et permissions

- Jira et Confluence sont-ils Cloud ou Data Center ?
- Quels serveurs MCP précis seront utilisés et quelles versions/outils exposent-ils ?
- Chaque MCP utilise-t-il un jeton individuel, une délégation OAuth ou un compte de service ?
- Comment les permissions sont-elles propagées et revalidées au moment de l'exécution ?
- Le Figma MCP choisi sait-il réellement créer, modifier et supprimer les nœuds nécessaires aux CJM ?
- Que doit proposer le produit si le Figma MCP est en lecture seule ?
- Quels champs Jira, types de tickets et workflows doivent être supportés pour chaque projet ?
- Comment les liens Confluence–Jira sont-ils écrits dans les deux systèmes ?

### 12.3 Données, IA et exploitation

- Quels espaces, projets et types de contenus sont indexables ?
- Quelle volumétrie initiale et quelle croissance sont attendues ?
- Quelle durée de conservation s'applique aux chunks, embeddings, conversations, propositions et audits ?
- Quelles contraintes de résidence, de confidentialité et de transfert de données s'appliquent à Groq et aux embeddings ?
- Quel modèle Groq, quel modèle d'embeddings multilingue et quel reranker seront retenus ?
- Quels seuils valident la qualité de recherche et la détection de doublons ?
- Quels objectifs de latence, disponibilité, RPO/RTO et nombre d'utilisateurs concurrents sont attendus ?
- Les contenus doivent-ils être pris en charge en français seulement, ou aussi en anglais et en arabe ?

## 13. Conditions de réussite du MVP

Le MVP est considéré comme fonctionnel lorsque, sur un projet pilote autorisé :

1. un utilisateur peut sélectionner des demandes Jira et les indexer sans fuite de permissions ;
2. il peut obtenir une analyse sourcée et des rapprochements de tickets ;
3. il peut générer, approuver et créer des Epics/User Stories dans Confluence ;
4. un élément validé peut être préparé, approuvé puis créé dans Jira sans doublon d'exécution ;
5. la liaison et la version Confluence–Jira sont traçables ;
6. toutes les mutations sont bloquées sans approbation explicite et refusées si les permissions ont changé ;
7. les processus/CJM Figma peuvent au minimum être consultés et utilisés comme sources ; l'écriture Figma n'est une condition de réussite que si la capacité MCP est confirmée comme faisant partie du MVP ;
8. les scénarios de refus d'accès, d'échec MCP, d'échec partiel et de tentative de prompt injection passent les tests convenus.
