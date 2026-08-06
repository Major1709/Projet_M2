# Revue securite ciblee du scaffold backend

> Note historique : cette revue décrit le scaffold avant la réorganisation modulaire d'août 2026. Les anciens chemins cités correspondent désormais principalement à `approvals/domain.py`, `approvals/workflow.py`, `agent/mutation_workflow.py`, `mcp/`, `core/identity.py` et `core/config.py`. Les constats restent applicables tant qu'une correction explicite n'est pas documentée.

**Reference :** `docs/security/mcp-security-design.md`  
**Perimetre :** `backend/` dans son etat du 2026-08-03  
**Nature :** revue statique ; aucun fichier de `backend/` n'a ete modifie

## 1. Verdict

Le scaffold pose une bonne separation conceptuelle entre le LLM, l'approbation, la revalidation et le gateway MCP. Il ne doit cependant pas etre connecte a Groq, Jira, Confluence, Figma ou un Knowledge MCP dans son etat actuel.

Le risque immediat est limite parce que :

- aucun adaptateur reseau Groq/MCP n'est implemente ;
- aucun endpoint ne declenche `ApprovalGuardedMCPExecutor` ;
- les seuls repositories et l'audit sont en memoire ;
- la configuration refuse volontairement de demarrer en mode `production` avec ces adaptateurs.

Ces protections font du code un scaffold de developpement raisonnablement fail-closed, pas un backend securise pour integration. Huit groupes d'ecarts sont bloquants avant d'activer un premier outil MCP de mutation.

## 2. Methode et limites

La revue a compare les modeles, routers, services, interfaces, executors, audit, configuration et tests aux exigences `SEC-*` du document de conception.

Le lancement de `python -m pytest` n'a pas ete possible dans l'environnement de revue : le module `pytest` n'est pas installe. Aucun package n'a ete installe et le resultat fonctionnel de la suite n'a donc pas ete revalide. Les six tests presents ont ete lus statiquement.

Les constats concernant OAuth, les serveurs MCP, Groq et le RAG portent sur l'absence d'implementation dans ce scaffold, pas sur des adaptateurs qui n'existent pas encore.

## 3. Synthese de couverture

| Domaine | Etat | Conclusion |
|---|---|---|
| Approbation immutable | Partiel, bonne base | snapshot canonique et revisions corrects ; liaison et expiration incompletes |
| Identite utilisateur | Developpement uniquement | en-tetes falsifiables ; OIDC, session et comptes sources absents |
| Revalidation source | Contrat partiel | appel avant mutation correct ; cible/version source non liees |
| Idempotence | Non conforme | cle fournie par l'appelant, aucune reservation durable ou reconciliation |
| Audit | Developpement uniquement | evenements utiles mais sink memoire et atomicite absente |
| Allowlist MCP | Absente | nom, classe et payload d'outil sont acceptes de l'entree |
| Prompt injection | Absente | seulement des interfaces, aucun traitement de contenu non fiable |
| Separation des tokens | Bonne direction, non implementee | aucun jeton dans les contrats LLM ; OAuth/token broker absents |
| Isolation RAG | Contrat seulement | provenance prevue ; aucun controle executable ni partition tenant |
| Exploitation | Fail-closed en production | demarrage production impossible avec les adaptateurs de developpement |

## 4. Constats bloquants

### B-01 — L'aperçu approuve et l'appel MCP ne reposent pas sur la meme commande canonique

**Exigences concernees :** SEC-APP-02, SEC-TOOL-02, D-APP-02.

**Preuves :**

- `backend/app/approvals/models.py:124-145` calcule le hash sur `target`, `payload`, `diff`, le nom d'outil et la classe d'action.
- `backend/app/approvals/models.py:64-66` exige l'identifiant et le titre d'une suppression uniquement dans `target`.
- `backend/app/orchestration/mutation_executor.py:61-67` construit pourtant l'appel MCP avec `arguments=proposal.payload` seulement ; `target` et `diff` ne sont pas transmis.
- `backend/app/approvals/models.py:43-67` ne verifie aucune coherence entre un identifiant present dans `target` et un identifiant eventuellement present dans `payload`.

**Impact :** une proposition peut afficher et hasher une cible A tandis que le payload execute designe une cible B. Pour un `DELETE`, la cible visible peut etre valide alors que l'adaptateur utilise un autre identifiant contenu dans le payload. L'approbation ne garantit donc pas encore que l'effet execute est celui affiche.

**Correction requise :**

1. introduire une commande canonique typee par outil, produite par le registre MCP ;
2. deriver la cible, l'apercu, le diff et les arguments MCP depuis cette commande unique ;
3. interdire les champs cibles dupliques ou contradictoires ;
4. recalculer et comparer le hash juste avant execution ;
5. lier le hash a `tool_version`, `schema_hash`, compte source, destination et preconditions ;
6. ajouter un test ou la cible d'apercu et la cible du payload different et verifier un refus.

### B-02 — L'identite est falsifiable et aucune delegation utilisateur source n'existe

**Exigences concernees :** SEC-AUTH-01, SEC-AUTH-02, SEC-AUTH-03, SEC-SVC-01.

**Preuves :**

- `backend/app/security.py:24-30` accepte `X-Tenant-ID` et `X-User-ID`, avec des valeurs par defaut, sans authentification.
- `backend/app/approvals/router.py:40-100` et `backend/app/conversations/router.py:18-44` utilisent directement cette dependance.
- `backend/app/security.py:8-15` ne porte que `tenant_id` et `user_id` ; il manque session, comptes sources et handles de grants.
- `backend/app/config.py:14-24` ne propose que `dev_headers` et refuse correctement ce mode en production.
- `backend/README.md:39-42` reconnait explicitement OIDC, OAuth et delegation comme TODO bloquants.

**Impact :** en developpement, tout client pouvant joindre l'API peut usurper un tenant et un utilisateur. En production, le serveur ne peut volontairement pas demarrer, ce qui evite une exposition accidentelle mais bloque toute integration MCP.

**Correction requise :** implementer OIDC Authorization Code + PKCE, session serveur, protection CSRF, reconstruction serveur du tenant, et liaison explicite `platform_user -> provider_subject -> grant_handle`. Le contexte de confiance doit contenir des handles opaques, jamais des access/refresh tokens.

### B-03 — Aucun registre allowlist ne fixe l'identite et la classe des outils

**Exigences concernees :** SEC-TOOL-01, SEC-TOOL-02, D-TOOL-01, D-TOOL-02.

**Preuves :**

- `backend/app/approvals/models.py:43-52` accepte du client `tool_name`, `action_class`, `payload` et `correlation_id`.
- `backend/app/mcp_gateway/models.py:34-41` transporte les memes valeurs sans definition d'outil versionnee.
- `backend/app/orchestration/llm.py:12-14` porte une liste `allowed_tool_names`, mais aucun policy engine ne la calcule ou ne l'impose.
- `backend/app/orchestration/llm.py:18-23` accepte egalement `action_class` dans la proposition du LLM.
- Aucun registre, schema par outil, empreinte de schema, endpoint allowliste, kill switch ou verification de version n'existe dans `backend/app/`.

**Impact :** la classe de risque est declarative. Un nom d'outil dangereux peut etre mal classe, un outil inconnu peut atteindre un futur gateway, et un changement de schema MCP ne serait pas detecte.

**Correction requise :** creer un registre serveur `ToolDefinition` en `default deny`. Le backend doit deriver `source_system`, `action_class`, schema, politique d'approbation, scopes, limites et destination depuis le registre. Les valeurs proposees par le LLM ou le client ne sont que des demandes, jamais une autorite.

### B-04 — La liaison d'approbation est partielle et le `decision_token` est expose

**Exigences concernees :** SEC-APP-01, SEC-APP-04, D-APP-01 a D-APP-03.

**Preuves :**

- `backend/app/approvals/models.py:86-113` ne contient ni `expires_at`, ni `tool_version`, ni compte source, ni session d'approbation, ni precondition source.
- `backend/app/approvals/models.py:107` stocke `decision_token` en clair.
- `backend/app/approvals/models.py:162-192` inclut `decision_token` dans `ActionProposalView`, retourne par la creation et le `GET`.
- `backend/app/approvals/router.py:61-100` ne possede pas de session authentifiee ni de controle CSRF ; le token est renvoye dans le corps de decision.
- `backend/app/approvals/service.py:145-159` controle correctement et en temps constant le token et la version, mais ne controle aucune expiration.
- `backend/app/approvals/models.py:126-144` lie le hash a une empreinte `tenant/user`, mais pas a la session, au compte source, a la version d'outil ou a une duree.

**Impact :** le token agit comme un bearer secret de developpement. Il peut etre copie depuis une reponse, reste valide sans limite de temps et n'est pas lie a la session ayant affiche l'apercu. La version optimiste empeche bien son rejeu apres consommation, mais pas son vol avant decision.

**Correction requise :** utiliser une approbation serveur liee a `actor`, tenant, session, action, payload hash, tool/schema version et expiration. Stocker seulement un hash du nonce si un nonce reste necessaire. Ne jamais retourner ce secret sur le endpoint de lecture general. Ajouter CSRF, TTL court, usage unique et confirmation renforcee pour suppression/batch.

### B-05 — La revalidation ne prouve ni la cible approuvee ni sa version courante

**Exigences concernees :** SEC-APP-03, D-APP-04, D-APP-05.

**Preuves :**

- `backend/app/orchestration/mutation_executor.py:68-84` appelle bien le verificateur juste avant le gateway et n'appelle pas le gateway si la decision est refusee.
- `backend/app/mcp_gateway/models.py:62-66` limite toutefois `PermissionCheck` au contexte minimal et a `MCPToolCall`.
- `backend/app/orchestration/mutation_executor.py:61-70` omet `proposal.target`, `diff`, compte source, source version/ETag et hash avant modification.
- `backend/app/approvals/models.py:86-113` ne stocke aucun `before_version`, `before_hash` ou ETag.
- `expected_version` dans `backend/app/orchestration/mutation_executor.py:34-49` protege seulement la version interne de la proposition, pas la ressource Jira/Confluence/Figma.

**Impact :** le controle permet un oui/non courant sur le payload, mais ne detecte pas qu'une page ou un ticket a change apres l'apercu. Il ne peut pas non plus prouver quel compte source a ete reautorise.

**Correction requise :** etendre `PermissionCheck` avec action, cible canonique, compte source, scopes, preconditions et hash approuves. Le verificateur doit relire les droits et la version dans la source, echouer ferme si la source est indisponible et produire une decision structuree avec sujet, ressource, version et horodatage. Un conflit impose nouvel apercu et nouvelle approbation.

### B-06 — L'idempotence n'est ni generee par le serveur ni durable

**Exigence concernee :** SEC-IDEM-01.

**Preuves :**

- `backend/app/orchestration/mutation_executor.py:30-37` recoit `idempotency_key` de l'appelant.
- `backend/app/orchestration/mutation_executor.py:86-96` transmet la cle sans reservation durable ; toute exception place l'action en `FAILED` sans distinguer un resultat externe ambigu.
- `backend/app/mcp_gateway/interfaces.py:28-34` ne definit qu'un parametre texte, sans protocole de reservation ou reconciliation.
- `backend/app/approvals/models.py:18-30` ne contient pas `UNKNOWN_RECONCILIATION_REQUIRED` ou des etats retryable/final distincts.
- `backend/app/approvals/in_memory.py:8-60` garantit l'atomicite uniquement dans un processus.
- `backend/app/main.py:17-21` et `backend/README.md:39-42` confirment l'absence de PostgreSQL, outbox et idempotence persistante.

**Impact :** un timeout apres creation externe peut etre classe `FAILED` sans savoir si l'objet existe. Une future reprise pourrait creer un doublon, et une cle differente pourrait contourner la deduplication si l'etat et la reservation ne sont pas atomiques.

**Correction requise :** generer la cle depuis l'action approuvee cote serveur, imposer une contrainte unique persistante, reserver l'execution atomiquement avec outbox, conserver les identifiants externes et introduire l'etat `UNKNOWN_RECONCILIATION_REQUIRED`. Aucun retry automatique apres resultat ambigu sans recherche source.

### B-07 — L'audit n'est pas durable, complet ni atomique avec les transitions

**Exigence concernee :** SEC-AUD-01, D-AUD-01.

**Preuves :**

- `backend/app/audit/in_memory.py:6-19` est un sink process-local explicitement non conforme.
- `backend/app/audit/models.py:19-29` utilise un `details: dict` libre et mutable ; aucun schema de redaction ou champ pour compte source, tool/schema version, session, preconditions, idempotence et trace fournisseur.
- `backend/app/approvals/service.py:60-71` persiste l'etat `APPROVED` avant d'ecrire l'audit. Si `append` echoue, la proposition reste approuvee.
- `backend/app/approvals/service.py:127-142` peut persister une revision puis n'auditer qu'ensuite.
- `backend/app/orchestration/mutation_executor.py:68-77` persiste `PERMISSION_CHECK`, appelle la source, puis audite. Une exception peut laisser un etat intermediaire sans chaine complete.
- `backend/app/orchestration/mutation_executor.py:78-84` place l'action en `DENIED` sans evenement de transition dedie apres le refus.

**Impact :** la non-repudiation et la reprise ne sont pas garanties. Plus critique, une approbation peut devenir executable meme si son evenement d'audit n'a jamais ete ecrit.

**Correction requise :** persister transition, evenement d'audit et outbox dans une transaction. L'executor doit verifier une chaine d'approbation durable avant tout appel. Utiliser des evenements structures, redaction centrale, stockage append-only et correlation complete. Une panne d'audit doit bloquer la mutation sans laisser un etat executable orphelin.

### B-08 — Prompt injection, sortie LLM et separation des tokens sont seulement des intentions d'architecture

**Exigences concernees :** SEC-LLM-01, SEC-LLM-02, SEC-AUTH-03, SEC-SEC-01.

**Preuves :**

- `backend/app/orchestration/llm.py:9-38` definit des contrats, mais aucun constructeur de contexte fiable, marquage de provenance, filtrage, validation d'intention ou nettoyage de sortie.
- `backend/app/orchestration/llm.py:18-23` laisse la sortie LLM proposer le nom, la classe et les arguments d'un outil.
- `backend/app/knowledge/interfaces.py:7-15` promet des passages prefiltrés et reautorises sans implementation.
- Aucun token broker, client OAuth, validation issuer/audience/resource, coffre ou mecanisme de redaction n'existe dans `backend/app/`.
- Point positif : `LLMRequest`, `LLMResponse`, `MCPToolCall` et `SecurityContext` ne contiennent aujourd'hui aucun access/refresh token.

**Impact :** connecter Groq ou une source maintenant creerait un chemin direct du contenu non fiable vers une proposition d'outil sans garde-fou executable. La non-propagation des tokens n'est pas testable tant que les adaptateurs n'existent pas.

**Correction requise :** avant le premier connecteur, ajouter un context builder qui separe instructions et donnees, provenance obligatoire, nettoyage HTML/Markdown, validation d'intention, schemas stricts, exposition minimale des outils et rendu echappe. Implementer un token broker avec grants opaques et jetons distincts par audience ; instrumenter un test prouvant que le jeton MCP n'est jamais le jeton aval.

## 5. Constats importants

### I-01 — Une proposition n'est pas rattachee a une conversation possedee par l'utilisateur

`backend/app/approvals/service.py:28-37` accepte `conversation_id` sans consulter le repository de conversations. `backend/app/conversations/router.py:39-44` applique pourtant correctement tenant et proprietaire lors d'une lecture.

**Recommandation :** verifier l'existence, le tenant et le proprietaire de la conversation au moment de proposer une action. Generer le `correlation_id` cote serveur ou le normaliser comme metadonnee non fiable.

### I-02 — Le futur filtre RAG est fourni dans l'objet de requete

`backend/app/knowledge/models.py:16-23` expose `allowed_scope_ids` dans `KnowledgeQuery`. `backend/app/knowledge/interfaces.py:10-15` recoit aussi le contexte, ce qui est une bonne direction, mais rien n'empeche encore le LLM ou un client de proposer un scope plus large.

**Recommandation :** retirer les scopes autorises de l'entree LLM publique. Les calculer dans un policy service depuis le tenant, le compte source et les permissions courantes, puis les injecter dans une commande interne. Tester le prefiltrage tenant/scope avant ANN et le controle final de chaque passage.

### I-03 — La machine d'etats ne couvre pas expiration, conflit source et reprise sure

`backend/app/approvals/models.py:18-30` declare `EXPIRED`, mais aucune horloge ne produit cette transition. Il manque un etat explicite de conflit source et les distinctions `FAILED_RETRYABLE`, `FAILED_FINAL` et `UNKNOWN_RECONCILIATION_REQUIRED` prevues par le design.

**Recommandation :** formaliser une table de transitions exhaustive et testee. Interdire `model_copy(update=...)` hors d'un agregat/service qui valide chaque transition.

### I-04 — Les entrees volumineuses et les boucles ne sont pas encore bornees

`backend/app/approvals/models.py:49-51` accepte des dictionnaires `payload`/`diff` sans limite de taille, profondeur ou nombre d'elements. `backend/app/orchestration/llm.py:12` ne borne pas le nombre ni la taille des messages. `max_steps` est heureusement limite a 20, mais aucun quota, rate limit, body limit, timeout ou kill switch n'existe.

**Recommandation :** limites de corps au reverse proxy et dans l'application, schemas fermes par outil, quotas utilisateur/tenant, timeouts, circuit breakers, limite de resultats et kill switch par MCP/outil.

### I-05 — Les tests couvrent le chemin heureux mais pas les invariants adversariaux

`backend/tests/test_approval_state.py:57-218` couvre consommation du token, conflits optimistes, revision, interdiction avant approbation et revalidation avant execution.

Il manque au minimum : mauvais tenant/utilisateur, token incorrect ou expire, cible/payload contradictoires, permission refusee/exception, changement de version source, deux executions concurrentes, cle differente pour meme action, timeout ambigu, panne d'audit, schema d'outil modifie, fuite de token et prompt injection.

### I-06 — Les objets imbriques marques `frozen` ne sont pas tous profondement immutables

`backend/app/audit/models.py:28` expose un dictionnaire mutable dans un modele fige. Les payloads des commandes d'entree sont aussi des dictionnaires avant canonicalisation. L'`ActionProposal` reduit correctement ce risque en stockant du JSON texte, mais l'audit et les contrats LLM/MCP restent susceptibles de mutation interne accidentelle.

**Recommandation :** structures typees et immutables, copie profonde/canonicalisation aux frontieres, et verification de hash lors du rechargement persistant.

## 6. Ameliorations ulterieures

Ces points viennent apres les blocants du prochain sprint :

1. MFA/step-up et separation des devoirs pour suppression permanente ou mutation de masse.
2. DPoP ou mTLS quand les fournisseurs le permettent, en complement de l'audience stricte.
3. Audit WORM ou chainage cryptographique, politique de retention et exports conformite.
4. Detection/classification avancee de prompt injection et quarantaine d'ingestion, sans remplacer les controles deterministes.
5. Partition physique RAG par domaine sensible et controle ACL de chaque noeud du graphe quand le graphe sera implemente.
6. Webhooks de revocation/suppression, caches de permissions a TTL court et exercices de reponse a incident.

## 7. Controles deja corrects

### C-01 — Echec ferme de la configuration production

`backend/app/config.py:18-24` refuse `memory` et `dev_headers` en production. Comme ce sont les seules options actuelles, le scaffold ne peut pas etre lance accidentellement comme backend de production. Ce controle doit rester jusqu'a disponibilite d'adaptateurs conformes.

### C-02 — Snapshot canonique et modele fige

`backend/app/approvals/models.py:86-113` fige `ActionProposal`. `backend/app/approvals/models.py:124-150` serialise le payload/diff de facon canonique et calcule un SHA-256 couvrant source, outil, classe, cible, payload, diff et empreinte du contexte.

### C-03 — Une revision cree une nouvelle proposition

`backend/app/approvals/service.py:95-143` supersede l'ancienne proposition et cree un nouvel ID, un nouveau snapshot, un nouveau hash et un nouveau token. Cela respecte le principe « modification = nouvelle approbation ».

### C-04 — Controle optimiste et anti-rejeu en memoire

`backend/app/approvals/in_memory.py:26-60` applique un compare-and-swap sous verrou. `backend/app/approvals/service.py:145-159` exige l'etat `PENDING_APPROVAL`, la version attendue et compare le token avec `hmac.compare_digest`. Les tests `backend/tests/test_approval_state.py:57-124` couvrent ces invariants.

### C-05 — Isolation tenant et proprietaire sur les lectures existantes

`backend/app/approvals/service.py:39-50` et `backend/app/conversations/router.py:33-44` requetent par tenant, verifient le proprietaire et retournent 404 pour eviter de confirmer l'existence d'une ressource d'un autre utilisateur.

### C-06 — Facade de mutation gardee et ordre revalidation puis appel

`backend/app/orchestration/mutation_executor.py:38-59` exige proposition `APPROVED`, meme approbateur, meme empreinte de contexte et classe de mutation. `backend/app/orchestration/mutation_executor.py:68-92` appelle le verificateur avant le gateway et echoue ferme sur une decision refusee. Le LLM ne possede pas de reference directe au gateway dans `backend/app/orchestration/llm.py`.

### C-07 — Interfaces sans credentials

`backend/app/orchestration/llm.py`, `backend/app/mcp_gateway/models.py` et `backend/app/mcp_gateway/interfaces.py` ne font circuler aucun jeton ou secret. Cette separation doit etre preservee lorsque le token broker sera ajoute.

### C-08 — Minimisation initiale de l'audit et provenance RAG prevue

`backend/app/approvals/service.py:167-181` journalise le hash plutot que le payload complet. `backend/app/knowledge/models.py:25-36` prevoit source, version, segment, URL et identifiant de decision d'autorisation pour chaque passage.

## 8. Matrice des exigences `SEC-*`

| Exigence | Etat scaffold | Preuve/conclusion |
|---|---|---|
| SEC-AUTH-01 | Non conforme hors dev | identite issue d'en-tetes : `security.py:24-30` |
| SEC-AUTH-02 | Absente | aucun OIDC/OAuth |
| SEC-AUTH-03 | Absente | aucun client/serveur MCP ou token broker |
| SEC-TOOL-01 | Absente | aucun registre allowlist |
| SEC-TOOL-02 | Non conforme | nom/classe/payload declares par l'entree |
| SEC-APP-01 | Partiel solide | etat APPROVED obligatoire, mais endpoint/session/expiration incomplets |
| SEC-APP-02 | Bloquant | cible d'apercu omise de l'appel MCP |
| SEC-APP-03 | Partiel | revalidation oui/non presente, version source absente |
| SEC-APP-04 | Partiel | version et usage unique presents ; expiration/session absentes |
| SEC-IDEM-01 | Absente | cle appelant, aucune persistance/reconciliation |
| SEC-RAG-01 | Contrat uniquement | aucune implementation de retrieval |
| SEC-RAG-02 | Absente | aucun graphe |
| SEC-LLM-01 | Contrat uniquement | aucun garde-fou ou adaptateur |
| SEC-LLM-02 | Absente | aucun nettoyage/rendu securise backend |
| SEC-SEC-01 | Non testable | aucun token ; aucune redaction/vault implementes |
| SEC-AUD-01 | Non conforme production | audit memoire, non transactionnel |
| SEC-SVC-01 | Non testable | mode d'identite MCP non implemente |
| SEC-OPS-01 | Absente | pas de quotas, timeout, kill switch ou alertes |

## 9. Plan recommande pour le prochain sprint

### Lot 1 — Fermer la commande executee

1. Registre allowlist versionne et schemas fermes.
2. Commande canonique unique pour apercu, hash, permission et execution.
3. Cible, compte source, tool/schema version et preconditions inclus dans le hash.
4. Tests adversariaux cible/payload, outil inconnu, mauvaise classe et schema change.

### Lot 2 — Rendre approbation et execution durables

1. PostgreSQL avec compare-and-swap transactionnel.
2. Approbation expiree, liee a la session et token stocke sous forme de hash.
3. Outbox, reservation idempotente serveur et etat de reconciliation.
4. Audit append-only dans la meme transaction logique.

### Lot 3 — Installer l'identite avant les connecteurs

1. OIDC et session BFF/CSRF.
2. Liaison des comptes sources et token broker a handles opaques.
3. Audience/resource et tokens MCP/aval distincts.
4. Revalidation reelle sur une sandbox source avec version/ETag.

### Lot 4 — Brancher un seul chemin pilote

Commencer par un outil `READ` et un outil `CREATE` Confluence dans un tenant de test. Ajouter prompt/data separation, nettoyage, quotas, kill switch et tests de fuite de tokens. Ne brancher Jira/Figma qu'apres validation de ce chemin.

## 10. Criteres go/no-go avant le premier MCP de mutation

Le branchement est **NO-GO** tant que tous les points suivants ne sont pas demonstrables par tests :

1. outil absent ou schema modifie refuse par defaut ;
2. cible affichee, hashee, revalidee et executee strictement identique ;
3. identite OIDC et compte source lies sans en-tete utilisateur falsifiable ;
4. approbation expiree, liee a la session et a usage unique ;
5. droits et version source revalides juste avant appel ;
6. cle idempotente serveur durable et timeout ambigu reconcilie ;
7. chaine d'audit durable presente avant execution ;
8. token MCP distinct du token aval et absent des prompts/logs ;
9. contenu source hostile incapable d'ajouter, approuver ou executer un outil ;
10. test inter-tenant et kill switch reussis.
