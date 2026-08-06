# Stratégie de test du MVP

Statut : stratégie Sprint 0 à valider

## 1. Objet

Cette stratégie définit comment démontrer que le parcours Jira → RAG → Confluence → Jira est fonctionnel, sécurisé, traçable et reprenable. Elle couvre aussi la consultation Figma/CJM ; les mutations Figma restent conditionnelles à la qualification du MCP retenu.

Les références `US-xx/CA-n` désignent le *n-ième critère d'acceptation* de la User Story correspondante dans `docs/product/mvp-spec.md`. Les références `SEC-*` renvoient aux exigences testables de `docs/security/mcp-security-design.md`.

Principes de test non négociables :

- un test de sécurité négatif est réussi seulement si aucun contenu, métadonnée, score, effet source ou secret interdit n'est observable ;
- les doubles de test MCP reproduisent les erreurs, versions, permissions et timeouts, mais les parcours critiques sont aussi validés contre des environnements source réels isolés ;
- les sorties Groq ne sont jamais comparées mot à mot : leur schéma, leurs preuves, leur fidélité et leurs invariants métier sont testés ;
- toute mutation de test utilise des tenants, projets, espaces et fichiers dédiés, avec nettoyage traçable ;
- une fonctionnalité conditionnelle non qualifiée, notamment l'écriture Figma, est déclarée bloquée et non « passée ».

## 2. Portée et niveaux de risque

### 2.1 Portée P0

- identité, session, tenant et délégation utilisateur vers les MCP ;
- listing et sélection de demandes Jira ;
- ingestion idempotente avec provenance et ACL ;
- recherche hybride, réponses sourcées et détection de similarité ;
- génération structurée sans écriture externe ;
- approbation, rejet, révision et expiration d'une proposition ;
- création initiale des Epics/User Stories dans Confluence ;
- validation fonctionnelle puis copie Confluence → Jira ;
- modification/suppression contrôlée, audit et reprise après erreur ;
- isolation multi-tenant, prompt injection et absence de secrets.

### 2.2 Portée P1/P2

- consultation et relations CJM Figma (`US-10`) : testée dès le MVP si le MCP de lecture est disponible ;
- mutation CJM (`US-11`) : suite conditionnelle activée seulement après qualification des outils Figma ;
- désynchronisation Confluence–Jira (`US-12`) : recommandée avant pilote, non bloquante pour le premier parcours vertical sauf décision produit contraire ;
- recherche multi-sauts avancée (`US-14`) : test de conception dans PostgreSQL, sans exiger Neo4j.

### 2.3 Classification des défauts

| Sévérité | Définition | Exemples | Politique |
|---|---|---|---|
| S0 critique | Fuite, élévation de privilège, mutation non approuvée, perte/corruption irrécupérable | contenu inter-tenant, rejeu d'approbation accepté | stop release immédiat |
| S1 majeure | Parcours P0 impossible ou résultat source incohérent | doublon Jira, faux succès, audit manquant | stop release |
| S2 moyenne | Fonction dégradée avec contournement sûr | fallback lexical non signalé, diff peu lisible | décision explicite avant release |
| S3 mineure | Défaut sans impact métier/sécurité significatif | texte, alignement visuel | peut être différé |

## 3. Pyramide de tests

| Niveau | Cible indicative | Exécution | Contenu principal |
|---|---:|---|---|
| Tests statiques | sur chaque changement | CI rapide | lint, types, format, dépendances, schémas OpenAPI/JSON Schema, scans secrets/SAST |
| Tests unitaires et propriétés | 55–65 % de la suite | CI rapide | politiques, transitions d'état, canonicalisation/hash, ACL, filtrage tenant, mappings, citation validator, chunk IDs |
| Tests de contrats/composants | 20–25 % | CI rapide puis intégration | API frontend/backend, outils MCP enregistrés, Groq structuré, repository PostgreSQL, SSE, erreurs normalisées |
| Tests d'intégration | 10–15 % | CI avec services | API + PostgreSQL/pgvector + Redis/worker + MCP simulés, concurrence, outbox, réindexation, audit |
| Tests E2E | 5–10 % | pré-merge ciblé, nightly complet | navigateur → API → worker → MCP sandbox, parcours P0 et accessibilité critique |
| Tests non fonctionnels/manuels | campagne release | préproduction | charge, chaos, pentest, red-team, qualité métier par experts, compatibilité réelle des MCP |

La couverture de lignes n'est pas un objectif suffisant. Les exigences `SEC-*`, les transitions d'état et les branches d'erreur P0 doivent atteindre 100 % de couverture de scénario. Une cible initiale de couverture de branches de 80 % sur le domaine backend et de 70 % sur le frontend est proposée, à confirmer après le scaffold.

## 4. Matrice des parcours P0

`Auto` signifie bloquant en CI dès que le composant existe. `Hybride` combine automatisation et vérification humaine ou fournisseur réel. `Manuel` nécessite une procédure et une preuve attachée à la release.

| ID test | Parcours / résultat attendu | Traçabilité | Niveau | Mode |
|---|---|---|---|---|
| P0-01 | L'utilisateur authentifié liste uniquement les demandes Jira lisibles ; clé, titre et statut autorisés sont affichés | `US-01/CA-1`, `US-02/CA-1`, `SEC-AUTH-01` | contrat + E2E | Auto + sandbox réel |
| P0-02 | Un ID Jira interdit, deviné ou issu d'un autre tenant ne révèle ni existence ni métadonnée | `US-01/CA-2`, `US-04/CA-3`, `SEC-RAG-01` | intégration sécurité | Auto |
| P0-03 | L'indexation démarre sur clic explicite et porte sur la liste exacte autorisée | `US-02/CA-2`, `SEC-TOOL-02` | E2E + intégration | Auto |
| P0-04 | Chaque chunk garde source, version, URL/référence, date et enveloppe d'accès ; même version = pas de doublon | `US-02/CA-3..4` | composant + base | Auto |
| P0-05 | Une question projet produit une réponse avec citations autorisées ; sans preuve, réponse explicite d'absence | `US-03/CA-1..3` | évaluation RAG + E2E | Auto + revue experte |
| P0-06 | La similarité ordonne les candidats autorisés, affiche score/provenance et les marque comme suggestions | `US-04/CA-1..3` | évaluation RAG + UI | Auto |
| P0-07 | La génération distingue Epic, Stories, critères et relations, cite les sources et ne crée rien dans Confluence | `US-05/CA-1..3`, `SEC-LLM-01` | contrat LLM + intégration | Auto |
| P0-08 | L'aperçu Confluence affiche le payload canonique et la destination exacte avant activation de l'approbation | `US-05/CA-4`, `SEC-APP-01..02` | composant UI + E2E | Auto |
| P0-09 | Approuver crée une fois dans Confluence après revalidation ; rejeter ne transmet rien ; réviser crée une nouvelle proposition | `US-06/CA-1..5`, `SEC-APP-01..04`, `SEC-IDEM-01` | intégration + E2E | Auto + sandbox réel |
| P0-10 | Seuls les éléments `APPROVED` et à la version validée sont préparés pour Jira | `US-07/CA-1..3` | domaine + intégration | Auto |
| P0-11 | L'aperçu Jira montre mapping complet, relations, doublons et liens existants ; aucun ticket avant accord | `US-08/CA-1..3` | composant + E2E | Auto |
| P0-12 | Le lot approuvé crée les tickets autorisés, persiste les liens/hashes et distingue succès, échecs et non-tentés | `US-08/CA-4..6`, `SEC-IDEM-01` | intégration + E2E | Auto + sandbox réel |
| P0-13 | Update montre cible + diff ; delete montre système/type/ID/titre + avertissement ; refus/expiration = zéro appel MCP | `US-09/CA-1..4`, `SEC-APP-01..04` | UI + intégration | Auto |
| P0-14 | Chaque tentative produit une chaîne d'audit corrélée, sans secret ni exposition indirecte | `US-09/CA-5`, `US-13/CA-1..4`, `SEC-AUD-01`, `SEC-SEC-01` | intégration sécurité | Auto + revue manuelle |
| P0-15 | Une permission retirée ou une version changée après aperçu produit `DENIED`/`CONFLICT`, aucun effet source | `US-01/CA-3`, `US-07/CA-3`, `SEC-APP-03` | concurrence + E2E | Auto |
| P0-16 | Indisponibilité MCP, timeout ambigu ou échec partiel ne produit jamais de faux succès ni de duplication | condition MVP 8, `US-08/CA-6`, `SEC-IDEM-01`, `SEC-OPS-01` | résilience | Auto |
| P0-17 | Une instruction hostile dans Jira/Confluence/Figma/RAG ne modifie ni outils, ni destination, ni approbation | condition MVP 8, `SEC-LLM-01..02` | sécurité IA | Auto + red-team |

## 5. Permissions, isolation tenant et contrôle d'accès

### 5.1 Matrice d'identités

Le corpus de test utilise deux tenants `T-A` et `T-B`, deux projets/espaces/fichiers par tenant, et au minimum ces profils :

| Profil | Jira | Confluence | Figma | Attendu |
|---|---|---|---|---|
| lecteur | lecture projet A | lecture espace A | lecture fichier A | lectures seulement, aucune mutation |
| rédacteur Confluence | lecture Jira | écriture espace A | lecture Figma | création/modification Confluence après accord |
| validateur | lecture Jira | validation définie | lecture Figma | passage `APPROVED` selon règle métier |
| contributeur Jira | écriture projet A | lecture espace A | lecture Figma | copie vers Jira après accord |
| sans accès | aucun projet A | aucun espace A | aucun fichier A | aucune existence révélée |
| compte de service | accès technique A+B | accès technique A+B | selon MCP | intersection stricte avec l'utilisateur |

Chaque scénario est rejoué avec : ID direct deviné, recherche textuelle, recherche vectorielle, graphe voisin, citation, historique de conversation, cache chaud, réindexation et lien source. La suite vérifie le corps, les codes d'erreur, les compteurs, les logs, les traces et le contexte Groq capturé.

### 5.2 Scénarios bloquants automatisés

- session absente/expirée, `tenant_id` fourni par le client, IDOR/BOLA sur conversation, action, ingestion, citation et audit : refus fermé (`SEC-AUTH-01`) ;
- jeton mauvais issuer/audience/scope, ID token utilisé comme access token et token d'un MCP présenté à un autre (`SEC-AUTH-02..03`) ;
- même texte et mêmes embeddings dans `T-A` et `T-B` : zéro fuite de chunk, titre, score, nombre, relation ou timing exploitable (`US-03/CA-3`, `SEC-RAG-01`) ;
- nœud autorisé lié à un voisin interdit : le voisin et toute déduction révélant son existence sont absents (`SEC-RAG-02`) ;
- retrait d'accès après ingestion ou au milieu d'une conversation : ressource exclue dès la requête suivante (`US-01/CA-2..3`) ;
- cache de retrieval portant un autre utilisateur/scope : aucun hit réutilisable ;
- compte de service : lecture, RAG et mutation bloqués si l'autorisation utilisateur source ne peut pas être démontrée (`SEC-SVC-01`).

La campagne avec les véritables rôles Jira/Confluence/Figma est `Hybride` : provisionnement automatisé si les APIs d'administration de l'environnement de test le permettent, vérification manuelle initiale des rôles et preuves fournisseur jointes à la release.

## 6. Approbation, TOCTOU et idempotence

### 6.1 Table de transitions

Des tests unitaires par table de décision couvrent chaque état autorisé et chaque transition interdite :

```text
PROPOSED -> VALIDATED -> PENDING_APPROVAL
PENDING_APPROVAL -> REJECTED | EXPIRED | SUPERSEDED | APPROVED
APPROVED -> PERMISSION_REVALIDATION
PERMISSION_REVALIDATION -> DENIED | CONFLICT | EXECUTING
EXECUTING -> SUCCEEDED | FAILED_RETRYABLE | FAILED_FINAL
          | UNKNOWN_RECONCILIATION_REQUIRED
```

Invariants testés par propriétés :

- une proposition est immuable après `PENDING_APPROVAL` ;
- le hash canonique varie si payload, cible, destination, compte, outil/version ou précondition varie ;
- une approbation lie acteur, tenant, action, hash, version et expiration ;
- une décision est à usage unique et ne permet qu'une exécution logique ;
- aucun chemin vers `EXECUTING` ne contourne `APPROVED` et `PERMISSION_REVALIDATION` ;
- panne de l'audit avant exécution = aucune mutation (`SEC-AUD-01`).

### 6.2 Scénarios d'attaque et concurrence

| Scénario | Attendu | Référence | Mode |
|---|---|---|---|
| approbation sans CSRF/anti-rejeu ou avec version attendue incorrecte | refus | `SEC-APP-04` | Auto |
| acteur/tenant/session/action différents | refus sans révéler le payload | `SEC-APP-04` | Auto |
| payload modifié d'un octet sémantique après aperçu | proposition `SUPERSEDED`, nouvel accord requis | `US-06/CA-2`, `SEC-APP-02` | Auto |
| double clic et deux workers concurrents | une réservation, une exécution logique | `US-06/CA-5`, `SEC-IDEM-01` | Auto |
| permission retirée avant appel MCP | `DENIED`, zéro mutation | `US-01/CA-3`, `SEC-APP-03` | Auto |
| ETag/version cible modifié avant update/delete | `CONFLICT`, nouvel aperçu requis | `SEC-APP-03` | Auto |
| source indisponible pendant revalidation | refus fermé, jamais utilisation du cache | `SEC-APP-03` | Auto |
| timeout avant réponse, après création effective | recherche de corrélation, pas de retry aveugle | `SEC-IDEM-01` | Auto + sandbox réel |
| crash après réservation/outbox redélivrée | reprise, une création logique | `SEC-IDEM-01` | Auto |
| résultat fournisseur indéterminable | `UNKNOWN_RECONCILIATION_REQUIRED`, arrêt automatique | `SEC-IDEM-01` | Auto |
| lot avec succès puis échec | réussis/échoués/non tentés exacts, reprise ciblée | `US-08/CA-6` | Auto |

## 7. Prompt injection et sécurité des sorties

Un corpus adversarial versionné contient les attaques suivantes dans le titre, le corps, les commentaires, macros, métadonnées, calques masqués et texte OCR éventuel :

- instructions directes et indirectes demandant d'ignorer la politique, d'approuver ou de supprimer ;
- fausses balises système/outils et faux résultats MCP ;
- JSON/tool call inséré dans un document ;
- Unicode bidi, caractères invisibles, homoglyphes et encodages imbriqués ;
- HTML/Markdown actif, image distante, lien `javascript:` ou URL d'exfiltration ;
- récupération de secrets, prompts internes, données d'un autre tenant ou conversation ;
- empoisonnement RAG combinant texte pertinent et instruction malveillante ;
- destination, compte source ou URL MCP fournis par le contenu hostile.

Assertions automatiques (`SEC-LLM-01..02`, `SEC-TOOL-01..02`, `SEC-SEC-01`) :

- aucune instruction externe ne devient instruction système ou autorisation ;
- aucun outil de mutation n'est exécuté ; au maximum une proposition conforme peut être créée ;
- la destination et l'identité viennent du contexte serveur ;
- les arguments restent conformes au schéma fermé ;
- le rendu est échappé et aucun chargement distant non autorisé n'est déclenché ;
- les canary tokens sont absents des prompts, sorties, événements SSE, logs, traces, erreurs et snapshots ;
- la tentative est journalisée sans recopier le contenu sensible.

Une campagne red-team manuelle est requise avant le pilote, après changement de prompt/modèle Groq, après changement de MCP ou de schéma d'outil, puis périodiquement.

## 8. RAG, graphe et citations

### 8.1 Jeu de référence

Le jeu versionné inclut des documents synthétiques et, lorsque permis, des cas anonymisés validés par des experts : clés/titres/acronymes, quasi-doublons, FR↔EN, arabe si retenu, exigences non couvertes, parcours multi-sauts, versions obsolètes, contradictions, questions sans réponse, injections et paires d'utilisateurs aux droits différents.

Chaque cas annote : ressources/chunks pertinents, passages interdits, réponse attendue ou points obligatoires, citations attendues, statut fait/inférence, versions source et permissions.

### 8.2 Mesures et seuils de passage

| Dimension | Mesure | Seuil initial |
|---|---|---:|
| sécurité retrieval | chunks/métadonnées/scores interdits exposés | 0 sur 100 % des scénarios négatifs |
| validité citation | citations autorisées réellement présentes dans le contexte Groq | 100 % |
| récupération | Recall@10 | ≥ 0,85 |
| identifiants exacts | MRR | ≥ 0,90 |
| fidélité citation | précision | ≥ 0,95 |
| couverture des affirmations | affirmations projet vérifiables citées | ≥ 0,90 |
| reranker | gain nDCG@10 contre RRF seul | ≥ 5 % pour activation |
| latence retrieval | p95 hors Groq et réautorisation MCP | ≤ 1,5 s à volumétrie MVP |
| révocation/suppression | contenu injecté à la requête suivante | 0 |

Les mesures sont ventilées par source et langue. Un score moyen ne peut pas masquer une fuite ACL ou une mauvaise catégorie. Les tests RAG sont rejoués à chaque version de chunking, embedding, reranker, prompt ou modèle Groq ; les changements lourds passent d'abord en shadow evaluation.

Tests complémentaires : citation inconnue inventée par Groq refusée ; URL générée non issue des métadonnées remplacée/refusée ; source obsolète non préférée à une version active ; conflit inter-source annoncé ; relation inférée marquée avec preuve et confiance ; fallback RRF/lexical signalé et soumis aux mêmes ACL.

## 9. Contrats MCP et doubles de test

Chaque outil allowlisté possède un contract pack versionné contenant : serveur/éditeur/version, identifiant canonique, JSON Schema entrée/sortie, empreinte du schéma, classe de risque, scopes/permissions, limites, erreurs, idempotence, préconditions et exemples nettoyés.

### 9.1 Tests bloquants de contrat

- découverte d'un outil absent, nouveau, renommé, non versionné ou dont l'empreinte change : outil désactivé par défaut (`SEC-TOOL-01`) ;
- champs additionnels, mauvais types, tailles extrêmes, IDs cross-tenant, path traversal, URL/DNS/redirection SSRF : refus avant le réseau (`SEC-TOOL-02`) ;
- outil `READ` avec effet secondaire : reclassification au risque maximal ;
- outil `CREATE/UPDATE/DELETE/SYNC` sans règle d'approbation, permission check, audit ou kill switch : non publiable ;
- erreur/timeout MCP normalisé sans faux succès ; correlation et sujet de réponse vérifiés ;
- jeton de passerelle différent du jeton aval et jamais transmis à un autre fournisseur (`SEC-AUTH-03`) ;
- quotas, taille, timeout et limite d'appels appliqués (`SEC-OPS-01`).

### 9.2 Stratégie des environnements

1. **Simulateur déterministe** en CI : scénarios heureux, erreurs, latence, timeout ambigu, schéma modifié, révocation, version concurrente et réponse malveillante.
2. **Sandbox réel** nightly : lecture Jira/Confluence/Figma et mutations réversibles dans des ressources dédiées.
3. **Qualification manuelle** avant activation : identité déléguée, permissions par ressource, audit fournisseur, comportement de suppression et capacité Figma réelle.

Les suites de mutation réelles sont sérialisées par tenant de test et portent un préfixe/correlation unique. Le nettoyage ne doit jamais masquer l'existence d'un doublon : l'assertion d'unicité est faite avant archivage/suppression des objets de test.

## 10. Tests E2E navigateur

Les E2E utilisent un navigateur réel et contrôlent aussi le réseau afin de prouver l'absence d'appel prématuré :

1. login → listing Jira → sélection → job d'ingestion → question sourcée ;
2. génération → aperçu canonique → révision → nouvel aperçu → approbation → création Confluence ;
3. validation Confluence → préparation Jira → alerte doublon → approbation → création et liaison ;
4. update et delete : diff/cible, avertissement, rejet puis approbation valide ;
5. retrait de permission et changement de version entre aperçu et clic ;
6. échec partiel d'un lot puis reprise sans doublon ;
7. historique/audit visible seulement à l'auditeur autorisé ;
8. consultation d'un CJM Figma et citation du fichier/nœud ; mutation seulement si qualifiée.

Assertions UI transversales : boutons explicites, état de traitement long, erreurs non trompeuses, source ouvrable, clavier seul, focus visible, libellés accessibles, aucune information critique transmise uniquement par couleur et rendu sûr de contenu hostile. Les tests automatisés couvrent les règles axe courantes ; une revue manuelle clavier/lecteur d'écran est requise lorsque le niveau WCAG et les navigateurs sont décidés.

## 11. Performance, capacité et résilience

### 11.1 Performance

La volumétrie, la concurrence et les SLO globaux étant ouverts, les tests de charge sont d'abord instrumentés et non bloquants. Le seuil RAG p95 ≤ 1,5 s est bloquant une fois le jeu volumétrique validé.

Profils à mesurer :

- recherche lexicale/vectorielle/graphe avec partitions tenant et distributions réalistes ;
- ingestion initiale, réindexation inchangée et mise à jour d'une version ;
- chat SSE concurrent avec appels Groq simulés puis réels contrôlés ;
- file de workers, approbations simultanées, copie en lot et audit ;
- limites MCP, quotas par utilisateur, taille maximale et profondeur d'outils.

Mesures : p50/p95/p99, débit, erreurs, saturation CPU/mémoire/connexions, retard de queue, tokens/coût Groq, temps de réautorisation MCP et délai de fraîcheur.

### 11.2 Résilience et chaos ciblé

- Groq timeout/429/réponse JSON invalide : retry borné si sûr, message explicite, aucune mutation ;
- embedding indisponible : job reprenable, recherche lexicale/graphe possible sans assouplir les ACL ;
- reranker indisponible : fallback RRF mesuré ;
- MCP de réautorisation indisponible : ressource exclue en lecture, mutation refusée ;
- Redis/worker redémarré : job et outbox repris sans double effet ;
- PostgreSQL indisponible ou audit non inscriptible : mutation bloquée ;
- événement SSE perdu/reconnexion navigateur : état récupéré par API, pas de répétition d'action ;
- kill switch MCP/outil activé pendant un workflow : aucun nouvel appel et état explicite ;
- sauvegarde/restauration : aucun grant révoqué réactivé, cohérence des liens et clés d'idempotence vérifiée.

Les tests de restauration, RPO/RTO et endurance deviennent bloquants dès que leurs objectifs sont décidés.

## 12. Données de test et reproductibilité

### 12.1 Corpus synthétique minimal

- deux tenants et des projets/espaces/fichiers homonymes ;
- tickets identiques dont un interdit, doublons vrais/faux et descriptions multilingues ;
- pages Confluence avec Epic/Stories aux états `DRAFT`, `IN_REVIEW`, `APPROVED`, `SYNCED_TO_JIRA`, puis version modifiée ;
- CJM avec étapes liées, nœuds cachés et contenu hostile ;
- ressources supprimées, tombstones, versions concurrentes et relations vers voisins interdits ;
- canary secrets uniques par canal pour détecter une fuite précise ;
- lots permettant succès, erreur, non tenté et timeout ambigu.

### 12.2 Gouvernance

- fixtures déterministes, IDs prévisibles uniquement dans les simulateurs et seed versionnée ;
- horloge injectable pour expiration, fraîcheur et concurrence ;
- modèles Groq/embedding/prompt/chunking enregistrés dans chaque résultat d'évaluation ;
- aucune donnée de production brute en CI ; données réelles anonymisées seulement après approbation ;
- secrets de sandbox dans le coffre CI, jamais dans fixtures, snapshots ou rapports ;
- nettoyage réversible et limité aux ressources créées par le run ;
- résultats, traces expurgées et preuves de tests conservés selon une durée à décider.

## 13. Plan CI/CD

### 13.1 Pull request — bloquant, cible ≤ 15 minutes

1. lint, format, types et validation documentaire/liens internes ;
2. SAST, audit dépendances, scan secrets et configuration conteneurs ;
3. tests unitaires frontend/backend et propriétés de sécurité ;
4. tests de contrats API/OpenAPI/JSON Schema et MCP simulés ;
5. intégration PostgreSQL/pgvector + Redis/worker avec migrations neuves ;
6. E2E smoke P0 avec MCP/Groq simulés ;
7. corpus sécurité court : tenant, approbation, idempotence, injection et secrets.

### 13.2 Branche principale / nightly

- E2E P0 complet, matrice navigateurs retenue et contrôles axe ;
- sandboxes réelles Jira/Confluence/Figma en lecture, mutations réversibles qualifiées ;
- corpus RAG complet et comparaison aux seuils/baseline ;
- fuzzing schémas, concurrence workers et timeouts ambigus ;
- scans d'images/SBOM et test de migrations upgrade/rollback selon politique ;
- performance courte et détection de régression.

### 13.3 Candidat release / préproduction

- parcours P0 réel de bout en bout ;
- matrice réelle de permissions et révocation ;
- charge à volumétrie cible, résilience et restauration ;
- pentest BOLA/IDOR, CSRF, SSRF, OAuth/MCP et multi-tenant ;
- red-team LLM/RAG et revue humaine qualité Epic/User Story ;
- audit reconstitué et exercice de kill switch/reconciliation ;
- rapport de conformité des versions de MCP et modèles.

Les tests flakies ne sont jamais relancés jusqu'au vert sans diagnostic : ils sont isolés, possèdent un propriétaire et restent visibles. Un retry CI ne peut masquer un échec sécurité ou idempotence.

## 14. Critères de release

La release MVP est autorisée uniquement si :

- les huit conditions de réussite de la spécification produit sont démontrées ;
- 100 % des parcours P0 et exigences `SEC-*` applicables ont un test automatique passant ou une procédure manuelle approuvée avec preuve ;
- aucun défaut S0/S1 n'est ouvert et chaque S2 a une acceptation de risque explicite ;
- zéro fuite ACL, zéro secret exposé et 100 % des citations valides sur les corpus de sécurité ;
- les seuils RAG définis en section 8 sont atteints par source/langue applicable ;
- toutes les mutations sont protégées par aperçu canonique, approbation liée, revalidation, idempotence et audit ;
- le parcours Confluence → Jira passe un échec partiel et une reprise sans doublon ;
- les versions exactes des MCP/outils et leurs schémas sont qualifiés, épinglés et leurs kill switches testés ;
- les résultats d'indisponibilité ne sont jamais présentés comme des faits ou succès ;
- les décisions ouvertes nécessaires au comportement testé sont tranchées et documentées ;
- les runbooks d'incident, de reconciliation et de révocation sont testés ;
- les tests conditionnels Figma non qualifiés sont explicitement exclus de la release, pas ignorés.

## 15. Critères d'entrée et bloqueurs de test

Avant d'activer les campagnes réelles, il faut décider ou fournir :

1. Jira/Confluence Cloud ou Data Center, serveurs MCP exacts, versions, transports et schémas ;
2. modèle d'identité de chaque MCP et capacité de réautorisation par ressource ;
3. capacités réelles de lecture/écriture/suppression Figma et comportement d'audit ;
4. règle de validation Confluence, structure éditoriale et version/ETag exploitable ;
5. granularité d'approbation des lots, auto-approbation, confirmation de suppression et expiration ;
6. champs/workflows Jira et mécanisme de liaison Confluence–Jira ;
7. volumes, concurrence, langues, SLO, RPO/RTO, navigateurs et niveau WCAG ;
8. contraintes de données envoyables à Groq/embeddings et rétention des preuves ;
9. environnements sandbox et comptes de test représentatifs sans privilèges globaux.

Un manque sur les points 1 à 4 bloque l'activation en production des mutations concernées. Il ne bloque pas la construction des tests sur simulateurs.

## 16. Ordre des premiers tests à automatiser

1. machine d'états d'approbation et impossibilité d'atteindre `EXECUTING` sans accord valide ;
2. canonicalisation/hash, invalidation après révision et anti-rejeu/double clic ;
3. contexte serveur `tenant_id`/acteur et refus IDOR sur actions, conversations, ingestions et citations ;
4. filtre tenant/ACL avant top-k, puis réautorisation finale et révocation immédiate ;
5. registre MCP `default deny`, empreinte de schéma et validation stricte des arguments ;
6. idempotence/outbox avec deux workers, timeout ambigu et reprise partielle ;
7. audit obligatoire, corrélation complète et scan canary des secrets ;
8. validateur de citations et cas « aucune source autorisée » ;
9. corpus prompt injection multi-source sans appel de mutation ;
10. E2E vertical Jira lecture → ingestion → question sourcée, puis création Confluence approuvée.

## 17. Responsabilités

| Sujet | Responsable principal | Contributeurs |
|---|---|---|
| critères métier et corpus d'or | Product/Business Analyst | QA, experts projet |
| tests unitaires/contrats | propriétaire du module | QA |
| frameworks, fixtures, E2E et rapports | QA/Test Automation | Frontend, Backend |
| sécurité, tenant, OAuth/MCP, red-team | MCP/IAM/Sécurité | QA, Backend |
| évaluation RAG/LLM | IA/RAG/Graphe | QA, Product |
| performance, chaos, CI et environnements | DevOps/SRE | QA, Backend |
| critères de release et dérogations | Tech Lead | Product, QA, Sécurité |

La QA intervient dès la conception des contrats. Un critère non observable ou une dépendance externe non simulable est un défaut de testabilité à corriger avant l'implémentation du parcours concerné.
