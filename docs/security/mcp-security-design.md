# Conception securite MCP, IAM et RAG

**Statut :** decisions Sprint 0 et contrat du pilote MCP en lecture seule
**Perimetre :** plateforme web conversationnelle, orchestrateur, Groq, Jira MCP, Confluence MCP, Figma MCP et Knowledge MCP
**Date de reference :** 2026-08-12

## 1. Objectif et invariants

Ce document definit la barriere de securite entre le LLM, les serveurs MCP et les systemes sources. Jira, Confluence et Figma restent les sources de verite. Le LLM propose des lectures ou des actions, mais ne constitue jamais une autorite d'identite, de permission ou d'approbation.

Les invariants suivants sont bloquants pour la mise en production :

1. Un utilisateur ne peut lire ou modifier que ce que son identite dans le systeme source lui autorise.
2. Le LLM ne recoit aucun secret, jeton OAuth, cookie de session ou droit implicite.
3. Tout outil MCP est refuse par defaut et doit etre inscrit dans une allowlist versionnee.
4. Toute creation, modification ou suppression est interceptee et exige une approbation explicite liee au contenu exact.
5. Les permissions sont revalidees dans le systeme source juste avant l'execution d'une mutation.
6. Un contenu Jira, Confluence, Figma ou RAG est une donnee non fiable, jamais une instruction de controle.
7. L'index RAG et le graphe ne peuvent pas elargir les droits du systeme source.
8. Toute decision d'autorisation, approbation et execution est auditable.

## 2. Statut des choix

Les termes sont utilises ainsi dans tout le document :

- **Decision** : contrainte retenue pour le MVP ; son non-respect bloque la livraison.
- **Recommandation** : choix souhaite, a confirmer selon le deploiement et les MCP retenus.
- **Question ouverte** : information manquante qui peut modifier la conception.

## 3. Architecture de confiance

### 3.1 Vue logique

```text
Navigateur
  |  session web HttpOnly + CSRF
  v
Frontend/BFF --------> Fournisseur OIDC de la plateforme
  |
  | identite interne + contexte de session
  v
Orchestrateur IA (Groq/LangGraph)
  |  proposition structuree, jamais de jeton
  v
MCP Gateway / Policy Enforcement Point
  |-- Tool registry et allowlist
  |-- Policy engine (utilisateur, tenant, ressource, action)
  |-- Approval engine
  |-- Token broker par utilisateur
  |-- Idempotency/outbox
  |-- Audit
  |
  +--> Jira MCP -------> Jira
  +--> Confluence MCP -> Confluence
  +--> Figma MCP ------> Figma
  +--> Knowledge MCP --> PostgreSQL/pgvector, puis graphe eventuel
```

Le MCP Gateway est le point d'application de politique unique pour les appels emis par l'assistant. Aucun appel reseau du LLM vers un MCP n'est autorise. Le client MCP appartient au backend ; Groq ne voit que les descriptions minimisees des outils et leurs resultats nettoyes.

### 3.2 Frontieres de confiance

Les frontieres explicites sont :

1. navigateur vers BFF ;
2. BFF vers services backend ;
3. orchestrateur vers MCP Gateway ;
4. gateway vers chaque serveur MCP ;
5. serveur MCP vers son API source ;
6. ingestion source vers RAG ;
7. RAG vers contexte du LLM ;
8. services vers coffre de secrets, audit et observabilite.

Chaque frontiere exige TLS, authentification de service, propagation d'un identifiant de correlation et validation stricte des donnees. Les reseaux sortants des MCP sont limites aux domaines officiels configures ; une URL, un `cloud_id`, un identifiant de tenant ou un endpoint fourni par le LLM ne peut pas definir une destination reseau.

### 3.3 Composants et responsabilites

| Composant | Responsabilites securite | Interdictions |
|---|---|---|
| BFF | session, CSRF, OIDC, liaison utilisateur-session | exposer des jetons au navigateur ou au LLM |
| Orchestrateur | selectionner un outil autorise, produire une proposition structuree | decider d'un droit, executer directement une mutation |
| MCP Gateway | allowlist, politique, approbation, revalidation, idempotence, audit | faire confiance au nom ou a la classification declares par le LLM |
| Token broker | resoudre un handle opaque vers un grant utilisateur | retourner un jeton au LLM, au frontend ou aux journaux |
| MCP source | valider le jeton MCP, appliquer le contexte utilisateur, appeler l'API cible avec un jeton distinct | transmettre tel quel un jeton recu vers une API aval |
| Knowledge MCP | filtrer avant recherche et pendant toute traversee du graphe | repondre a partir d'un chunk non autorise ou d'un autre tenant |

**Decision D-ARCH-01 :** tous les outils accessibles au LLM passent par le gateway, y compris les outils de lecture.

**Decision D-ARCH-02 :** les controles deterministes du gateway ne peuvent pas etre desactives par un prompt, un outil MCP, une page Confluence, un ticket Jira ou un noeud Figma.

## 4. Identite, OIDC et OAuth

### 4.1 Identite de la plateforme

OIDC authentifie l'utilisateur de la plateforme. Le backend valide au minimum la signature, `iss`, `aud`, `exp`, `iat` et `nonce`, puis cree un identifiant interne stable. L'ID Token prouve une authentification ; il n'est pas utilise comme jeton d'acces vers un MCP ou un systeme source.

Le navigateur utilise une session serveur avec cookie `Secure`, `HttpOnly` et `SameSite`. Les endpoints qui changent un etat utilisent une protection CSRF. Le backend ne stocke pas d'access token dans `localStorage` ou `sessionStorage`.

### 4.2 Liaison des comptes sources

Un enregistrement explicite lie :

```text
platform_user_id
tenant_id
provider = jira | confluence | figma
provider_tenant_id / cloud_id
provider_subject_id
grant_handle
granted_scopes
created_at / last_verified_at / revoked_at
```

Le `grant_handle` est opaque et ne contient pas le jeton. Un utilisateur ne peut ni saisir ni remplacer `provider_subject_id`, `provider_tenant_id` ou `grant_handle` dans un prompt ou un appel d'outil.

### 4.3 Flux OAuth

**Decision D-IAM-01 :** utiliser Authorization Code avec PKCE `S256`, `state` et, pour OIDC, `nonce`. Valider exactement les URI de redirection et l'issuer attendu avant d'echanger le code. Refuser l'Implicit Grant et le Resource Owner Password Credentials Grant.

**Decision D-IAM-02 :** demander les scopes minimaux, par fournisseur et par fonction. Les scopes d'ecriture sont obtenus uniquement quand une fonction d'ecriture est activee ; un scope ne remplace jamais la permission metier courante dans Jira, Confluence ou Figma.

**Decision D-IAM-03 :** le contexte d'autorisation transmis au gateway contient au minimum `platform_user_id`, `tenant_id`, `session_id`, `conversation_id` et les handles de compte autorises. Il est signe, court, non rejouable au-dela de sa duree et cree par le backend, jamais par le LLM.

### 4.4 Jetons MCP et non-propagation naive

Pour chaque MCP distant, le client MCP obtient un access token dont l'audience est l'URI canonique de ce serveur. Le serveur MCP valide `iss`, `aud`, `exp`, `nbf`, signature et scopes. Conformement a MCP `2026-07-28`, le client inclut toujours le parametre OAuth `resource`, identique a l'URI canonique du serveur MCP, dans les requetes d'autorisation et de token.

Si un MCP appelle Jira, Confluence ou Figma, il agit comme client OAuth distinct de cette API. Il utilise un access token aval distinct, emis pour l'audience du fournisseur et rattache au grant du meme utilisateur.

```text
Jeton session/OIDC != jeton MCP Jira != jeton API Jira
Jeton MCP Jira      != jeton MCP Confluence
Jeton utilisateur A != jeton utilisateur B
```

**Decision D-IAM-04 :** le token passthrough est interdit. Un jeton recu par le MCP ne doit jamais etre transfere tel quel a Jira, Confluence, Figma ou un autre MCP.

**Decision D-IAM-05 :** le LLM, le navigateur et le service d'audit ne recoivent jamais les access tokens ou refresh tokens. Seuls le token broker et le connecteur concerne peuvent resoudre un grant opaque.

**Recommandation R-IAM-01 :** utiliser des access tokens courts, des refresh tokens avec rotation/revocation, et des jetons contraints a l'emetteur ou a la preuve de possession si les fournisseurs et MCP le permettent.

## 5. Politique des outils MCP

### 5.1 Allowlist et registre

Le registre versionne de chaque outil est materialise par un paquet de contrat immutable. Il contient :

- identifiant du serveur, editeur, endpoint canonique, transport et versions MCP autorisees ;
- identifiant canonique de l'outil, version et empreintes SHA-256 des schemas d'entree et de sortie ;
- description statique approuvee ;
- categorie de risque ;
- scopes et permissions sources requis ;
- contraintes de parametres et destinations autorisees ;
- type de ressources lu ou modifie ;
- politique d'approbation et de reauthentification ;
- volume maximal, delai, taux et taille de resultat ;
- caractere reversible, preconditions et mecanisme d'idempotence ;
- proprietaire, date de revue, version de politique et kill switch.

Le catalogue renvoye par `tools/list` est compare au paquet de contrat mais ne le
modifie jamais. Un outil inconnu est ignore et audite. Un outil attendu absent,
renomme ou dont un schema differe est bloque jusqu'a une nouvelle qualification
humaine. Les annotations MCP, notamment `readOnlyHint`, sont des indications non
fiables et ne remplacent jamais la classification locale.

**Decision D-TOOL-01 :** politique `default deny`. La decouverte dynamique MCP ne rend jamais automatiquement un nouvel outil accessible au LLM. Toute apparition, disparition ou modification de schema bloque l'outil jusqu'a revue et tests.

**Decision D-TOOL-02 :** le gateway valide les arguments avec un schema ferme : types, tailles, enumerations, identifiants, champs additionnels interdits et URLs limitees a une allowlist. Il reconstruit les champs d'identite et de tenant depuis la session.

### 5.2 Classification

| Classe | Exemples | Regle |
|---|---|---|
| `READ` | rechercher/lire/lister un ticket, une page ou un fichier | execution directe apres autorisation ; limite et audit |
| `CREATE` | creer une page, Epic, User Story, commentaire, lien ou noeud | apercu exact et approbation obligatoire |
| `UPDATE` | modifier, deplacer, transitionner, lier/delier, changer des droits | diff/preconditions et approbation obligatoire |
| `DELETE` | supprimer, archiver, vider une corbeille, retirer un lien structurant | cible explicite, impact et approbation renforcee |

Un outil en lot herite du risque maximal de ses sous-actions. Un outil de lecture qui declenche un effet secondaire est classe selon cet effet. Les exports massifs restent `READ` mais requierent une politique specifique de volume et, selon la sensibilite, une reauthentification.

L'indexation RAG declenchee par le bouton de selection est une ecriture interne. Le clic peut constituer l'approbation uniquement s'il est lie a la liste exacte des ressources, au tenant et a une duree limitee. Si le LLM propose lui-meme l'indexation, elle suit le flux `CREATE/UPDATE`.

### 5.3 Exposition minimale au modele

Le LLM ne voit, a chaque tour, que les outils necessaires a l'intention courante et deja permis pour le tenant. Les outils administratifs, de gestion des droits, de secrets, de configuration MCP et de purge globale ne sont jamais exposes au modele.

### 5.4 Profil qualifie du pilote en lecture seule

Le premier pilote utilise uniquement les serveurs distants officiels suivants :

| Serveur | Endpoint canonique | Mode d'identite | Statut |
|---|---|---|---|
| Atlassian Rovo MCP GA | `https://mcp.atlassian.com/v1/mcp` | OAuth 2.1 par utilisateur | retenu pour Jira et Confluence Cloud |
| Figma Remote MCP | `https://mcp.figma.com/mcp` | OAuth par utilisateur | retenu sous reserve d'admission du client |

L'endpoint Atlassian Preview, notamment
`https://mcp.atlassian.com/v1/mcp/preview`, est interdit. Ses outils et schemas
peuvent changer sans stabilite suffisante pour une allowlist de production. Une
URL de site Jira, Confluence ou Figma n'est jamais un endpoint MCP.

La version protocolaire de reference est MCP `2026-07-28`, version finale publiee
le 28 juillet 2026. Le transport distant est Streamable HTTP :

- chaque message est un `POST` independant ;
- le coeur du protocole est sans session et aucun `Mcp-Session-Id` n'est cree ;
- `MCP-Protocol-Version`, `Mcp-Method` et, lorsque requis, `Mcp-Name` sont presents ;
- les valeurs des en-tetes et du corps sont comparees et toute divergence est refusee ;
- les reponses JSON et SSE liees a la requete respectent le meme budget de temps et de taille ;
- aucun abonnement, sampling, prompt, elicitation ou chargement de ressource MCP n'est active dans le pilote.

Une compatibilite avec `2025-11-25` ne peut etre activee que dans un paquet de
contrat propre au serveur, apres qualification reelle. Aucun downgrade
heuristique ou silencieux n'est autorise.

#### 5.4.1 Allowlist Atlassian

Seuls les outils suivants peuvent etre inscrits comme `READ` :

```text
atlassianUserInfo
getAccessibleAtlassianResources
getVisibleJiraProjects
searchJiraIssuesUsingJql
getJiraIssue
getJiraIssueRemoteIssueLinks
getConfluenceSpaces
getPagesInConfluenceSpace
getConfluencePage
getConfluencePageDescendants
searchConfluenceUsingCql
```

Les scopes demandes sont limites a ceux requis par ce profil :

```text
read:jira-work
search:jira-work
read:page:confluence
read:space:confluence
read:hierarchical-content:confluence
search:confluence
```

Dans l'administration Atlassian, `Read` et `Search` sont autorises uniquement
pour Jira et Confluence ; `Write` reste bloque. L'option qui appliquerait
automatiquement une permission aux futures additions reste desactivee. Les
outils d'ecriture, commentaires non requis, recherche d'utilisateurs, Compass,
Jira Service Management, Bitbucket, Rovo, Teamwork Graph, ainsi que les outils
generiques `discover` et `execute`, sont refuses par defaut.

Les sites fournis pour le pilote sont deux hotes Atlassian Cloud distincts : un
site Jira et un site Confluence. Ils sont traites comme deux liaisons de source
potentiellement differentes. Le backend appelle
`getAccessibleAtlassianResources`, presente les sites accessibles a l'utilisateur
hors du contenu LLM, puis persiste le `cloudId` choisi dans le binding opaque. Un
`cloudId`, un hote ou un compte transmis dans un prompt ou des arguments d'outil
est refuse ; le gateway reinjecte exclusivement la valeur du binding serveur.

#### 5.4.2 Allowlist Figma

Seuls les outils suivants peuvent etre inscrits comme `READ` :

```text
whoami
get_metadata
get_design_context
get_screenshot
get_variable_defs
```

Le binding Figma contient le sujet authentifie, la cle du fichier approuve et le
noeud ou sous-arbre autorise. Ces valeurs sont derivees cote serveur du lien
selectionne puis normalisees ; le LLM ne peut ni changer de fichier ni elargir le
sous-arbre. Pour le pilote, `nodeId` est obligatoire, y compris lorsque l'outil
Figma le rend optionnel.

Tous les autres outils sont refuses. En particulier :

- `use_figma` est refuse en entier car il peut inspecter, creer, modifier et supprimer ;
- `create_new_file`, `add_code_connect_map`, `send_code_connect_mappings`,
  `generate_diagram`, `generate_figma_design` et `upload_assets` sont des mutations ;
- `download_assets` est refuse car il renvoie des URL temporaires qui ajouteraient
  un chemin de telechargement et d'exfiltration ;
- `get_libraries`, `search_design_system`, `list_shader_effects` et
  `list_shader_fills` elargissent la lecture au-dela du fichier connecte.

Le serveur Figma n'accepte actuellement que les clients presents dans son
catalogue. L'admission du backend Project Knowledge Assistant, ou la procedure
officielle equivalente, est donc un blocage externe avant un test reel. La
connexion d'un plugin de developpement deja admis ne vaut pas qualification du
client produit.

#### 5.4.3 Limites, SSRF et resultats

Le profil pilote applique les limites maximales suivantes :

```text
connexion reseau              3 secondes
appel MCP complet            30 secondes
resultat structure ou texte   2 Mio
image Figma                   8 Mio
appels MCP par tour           3
retry automatique             aucun
```

Les recherches Jira et Confluence imposent une pagination et une taille maximale
dans leur schema local. Une reponse plus grande, compressee de facon abusive,
mal formee ou hors schema est refusee, jamais tronquee silencieusement avant le
controle de securite.

Les endpoints sont des constantes admin sans userinfo, query string ni fragment.
HTTPS et le port attendu sont obligatoires, les redirections sont desactivees et
la resolution DNS refuse les destinations privees, loopback, link-local et
metadata. La decouverte OAuth part uniquement de l'endpoint MCP fixe et chaque
issuer est valide contre la configuration approuvee. Une URL renvoyee dans le
contenu d'un outil reste une donnee non fiable et n'est jamais telechargee
automatiquement.

Le client verifie l'identifiant JSON-RPC, le type de contenu, la version
protocolaire, le schema de sortie, les tailles, le MIME des images et la
correlation avec la requete. Il traduit ensuite la reponse dans un modele interne
minimal avec provenance. Le resultat MCP brut n'est transmis ni au LLM ni au
frontend.

#### 5.4.4 Audit des lectures

Chaque lecture exige une trace append-only disponible avant l'appel. Une panne de
l'audit bloque le pilote en echec ferme. La trace contient uniquement :

```text
date UTC, tenant, utilisateur, session et conversation
binding fournisseur opaque
serveur, outil, version MCP, version de politique et schema hash
hash des arguments et correlation_id genere cote serveur
decision, duree, taille, nombre d'objets et erreur normalisee
```

Elle ne contient jamais le payload, le contenu source, les prompts, les requetes
JQL/CQL, les URL temporaires, les cookies, les jetons ou les en-tetes
d'autorisation.

## 6. Interception et approbation des mutations

### 6.1 Machine d'etats

```text
PROPOSED
  -> VALIDATED
  -> PENDING_APPROVAL
       -> REJECTED
       -> EXPIRED
       -> SUPERSEDED
       -> APPROVED
            -> PERMISSION_REVALIDATION
                 -> DENIED
                 -> CONFLICT
                 -> EXECUTING
                      -> SUCCEEDED
                      -> FAILED_RETRYABLE
                      -> FAILED_FINAL
                      -> UNKNOWN_RECONCILIATION_REQUIRED
```

### 6.2 Contenu lie a l'approbation

Le gateway normalise une `ActionProposal` immutable :

```text
action_id, tenant_id, actor_id, provider_account_id
tool_id, tool_version, operation_class
target_ids, destination/project/space/file
canonical_payload
before_version + before_hash (UPDATE/DELETE)
expected_diff
idempotency_key
created_at, expires_at
payload_hash
```

L'interface d'approbation est generee depuis ce payload canonique, pas depuis un texte libre du LLM. Elle affiche la cible, la destination, les champs exacts, les effets en lot, le diff pour une modification et l'impact pour une suppression. Le rendu echappe HTML/Markdown, ne charge pas de ressources distantes et ne masque aucun champ approuve.

**Decision D-APP-01 :** l'approbation est emise par un endpoint serveur protege par session et CSRF. Une phrase presente dans un document source ou une sortie d'outil ne peut pas approuver. Un simple message de chat n'est acceptable que si l'interface le rattache sans ambiguite a un unique `action_id` et affiche a nouveau le payload lie.

**Decision D-APP-02 :** l'approbation lie `actor_id`, `tenant_id`, `action_id`, `payload_hash`, `tool_version` et expiration. Toute modification, meme mineure, cree une nouvelle proposition et annule l'approbation precedente.

**Decision D-APP-03 :** une approbation est a usage unique. Elle expire apres une duree courte configurable. Une suppression permanente ou une mutation de masse exige une confirmation renforcee ; preferer une suppression reversible quand le fournisseur le permet.

### 6.3 Revalidation et concurrence

Avant execution, un worker de confiance :

1. recharge l'action et l'approbation depuis la base ;
2. verifie leur etat, identite, tenant, hash, version d'outil et expiration ;
3. revalide le grant OAuth et les permissions actuelles dans le systeme source ;
4. relit la cible et compare sa version/ETag/hash aux preconditions approuvees ;
5. refuse si le contenu, les permissions, le compte source ou la destination ont change ;
6. execute avec idempotence ;
7. verifie et journalise le resultat source.

**Decision D-APP-04 :** un cache de permissions peut accelerer l'affichage, mais ne peut pas autoriser une mutation. Si la source ne permet pas une verification fiable ou est indisponible, la mutation echoue fermee.

**Decision D-APP-05 :** les modifications utilisent un controle de concurrence optimiste lorsque la source expose une version ou un ETag. Un conflit provoque un nouvel apercu et une nouvelle approbation.

## 7. Idempotence et fiabilite d'execution

La cle d'idempotence est generee par le serveur a partir de l'action approuvee, jamais par le LLM. Une contrainte unique en base interdit deux executions logiques du meme `action_id`.

Le pattern transactionnel recommande est :

1. enregistrer l'intention approuvee et un message outbox ;
2. reserver atomiquement la cle d'idempotence ;
3. appeler le MCP avec `action_id`/cle de correlation ;
4. enregistrer l'identifiant et la version renvoyes par la source ;
5. en cas de timeout ambigu, rechercher/reconcilier avant toute nouvelle creation.

Quand le fournisseur accepte une cle native, elle est transmise. Sinon, le connecteur utilise un marqueur de correlation ou une table de correspondance et recherche l'objet avant de retenter. Une action `UNKNOWN_RECONCILIATION_REQUIRED` ne doit pas etre rejouee automatiquement.

Les actions Confluence vers Jira conservent au minimum l'identifiant Confluence, la version et le hash approuves, la cle Jira, la date, l'auteur et l'`action_id`.

## 8. Audit et non-repudiation operationnelle

Le journal d'audit est append-only, separe des logs applicatifs et accessible selon le moindre privilege. Chaque evenement contient :

- date UTC synchronisee, correlation et trace ;
- utilisateur plateforme, tenant et compte source ;
- session et conversation ;
- outil, MCP, version, classification et schema hash ;
- identifiants de ressources et provenance ;
- decision de politique et raison ;
- controles de permission avant proposition et juste avant execution ;
- action, payload hash, preconditions et diff hash ;
- approbateur, horodatage, expiration et methode d'approbation ;
- cle d'idempotence, resultat, identifiant/version source et erreur normalisee ;
- decisions des garde-fous et alertes de securite.

Les jetons, cookies, secrets, mots de passe, en-tetes `Authorization` et contenus non necessaires sont redactes avant journalisation. Les prompts et payloads sensibles sont conserves selon une politique de minimisation : metadonnees et hashes dans l'audit, eventuel snapshot chiffre dans un depot a acces restreint avec retention definie.

**Decision D-AUD-01 :** toute mutation doit produire une chaine d'evenements complete de la proposition au resultat. Une panne d'audit empeche l'execution des mutations, sauf procedure d'urgence formellement approuvee et tracee hors bande.

**Recommandation R-AUD-01 :** utiliser un stockage immuable/WORM ou un chainage cryptographique des lots, une retention reglementaire definie et des alertes sur les ruptures de sequence.

## 9. Secrets et jetons

Les secrets applicatifs, cles de chiffrement, refresh tokens et credentials de service sont conserves dans un coffre de secrets. Les refresh tokens sont chiffres par enveloppe avec une cle KMS/HSM, une cle de donnees distincte et un contexte associe (`tenant_id`, `user_id`, fournisseur). Seul le token broker possede le droit de dechiffrer le grant requis.

Controles obligatoires :

- separation des cles par environnement et rotation documentee ;
- acces machine-to-machine par identite de workload, pas par secret partage statique si possible ;
- acces humain exceptionnel, approuve et audite ;
- redaction centralisee avant logs, traces, erreurs et retours d'outil ;
- jamais de secret dans Git, image de conteneur, prompt, base vectorielle ou variable frontend ;
- chiffrement des sauvegardes et test de restauration ;
- revocation des grants lors de la deconnexion du fournisseur, du depart d'un utilisateur ou d'un incident ;
- rotation immediate et investigation si un token apparait dans un log.

**Recommandation R-SEC-01 :** ne conserver en variable d'environnement de production que des references courtes vers le coffre, pas les refresh tokens ni les cles maitresses.

## 10. Prompt injection et sorties non fiables

Jira, Confluence et Figma contiennent du texte, des macros, commentaires, pieces jointes, metadonnees, calques caches et images potentiellement hostiles. Les sorties MCP et les chunks RAG sont egalement non fiables.

La defense est architecturale et multicouche :

1. marquer clairement les donnees externes et les separer des instructions systeme ;
2. ne jamais laisser un contenu recupere ajouter un outil, un droit, une approbation ou une destination ;
3. nettoyer HTML/Markdown, URLs, caracteres invisibles, metadonnees et contenu actif avant affichage ou contexte ;
4. analyser et mettre en quarantaine les contenus suspects a l'ingestion sans considerer un filtre comme une preuve de securite ;
5. limiter les chunks, leur provenance et les outils disponibles au strict besoin du tour ;
6. valider tout appel d'outil et toute sortie avec schemas, politiques et contraintes deterministes ;
7. comparer l'action proposee a l'intention utilisateur d'origine, hors du contenu externe non fiable ;
8. presenter l'approbation depuis le payload canonique echappe ;
9. ne jamais inclure secrets, instructions internes sensibles ou donnees d'autres utilisateurs dans le contexte ;
10. journaliser et alerter sur les tentatives d'injection, sans executer automatiquement une instruction contenue dans la source.

Une approche a deux niveaux est recommandee pour les actions sensibles : un composant de lecture sans outil de mutation extrait des faits structures depuis les sources non fiables ; le composant habilite a proposer une action ne recoit que ces faits et reste soumis au gateway. Un classifieur peut completer cette defense, jamais remplacer les controles deterministes.

**Decision D-LLM-01 :** une sortie Groq est traitee comme une entree non fiable. Elle ne peut ni creer une approbation, ni selectionner un compte source arbitraire, ni contourner le schema du tool registry.

**Decision D-LLM-02 :** les resultats rendus dans le chat sont echappes et les liens/images distants sont neutralises ou passes par une politique stricte pour eviter l'exfiltration via HTML/Markdown.

## 11. Confused deputy et appels aval

Le confused deputy est evite en liant chaque action a quatre identites : utilisateur plateforme, tenant plateforme, compte source et ressource MCP cible.

Controles :

- validation d'audience de chaque jeton et usage du parametre OAuth `resource` ;
- interdiction du token passthrough ;
- token aval distinct et limite au fournisseur ;
- correspondance serveur-side entre utilisateur et compte source ;
- intersection entre scopes, politique plateforme et permissions source ;
- destination/tenant choisis dans une configuration admin, jamais dans du texte LLM ;
- protection SSRF : HTTPS, allowlist d'hotes, resolution DNS/IP controlee, blocage des IP privees/metadata si non requises, pas de redirections vers un hote non autorise ;
- authentification mutuelle ou identite de workload entre gateway et MCP internes ;
- reponse MCP rattachee a la requete et au sujet attendus ;
- aucune reutilisation d'un resultat ou handle appartenant a une autre session, utilisateur ou tenant.

## 12. Isolation RAG et graphe de connaissances

### 12.1 Ingestion

Chaque objet et chunk conserve :

```text
tenant_id, source_system, source_tenant_id
source_object_id, source_version, source_url
project/space/file scope
ACL/provenance snapshot, indexed_by, indexed_at
content_hash, embedding_model_version
security_labels, deleted_at
```

L'indexation verifie que l'utilisateur ayant clique sur le bouton peut lire chaque ressource selectionnee. La liste exacte est liee a l'autorisation d'indexation. L'ingestion ne suit pas automatiquement des liens vers un autre espace, projet, fichier ou tenant sans nouveau controle.

### 12.2 Recherche

**Decision D-RAG-01 :** isolation physique ou logique forte par tenant. Toutes les requetes incluent un filtre de tenant non modifiable par le LLM.

**Decision D-RAG-02 :** l'ensemble autorise est applique avant ou pendant la recherche vectorielle, pas seulement apres le classement. Une verification finale est faite sur chaque chunk avant de le transmettre au LLM. Si le moteur ne garantit pas un prefiltrage fiable, utiliser des index/partitions par domaine de permission ou une recherche en deux etapes sur IDs autorises.

**Decision D-RAG-03 :** une traversee de graphe revalide les ACL de chaque noeud et contenu retourne ; l'autorisation du noeud de depart ne se propage pas automatiquement aux voisins.

**Decision D-RAG-04 :** une revocation ou suppression source invalide rapidement le cache de permissions et rend les chunks inaccessibles. Les webhooks sont souhaites, mais une verification source courte et un mecanisme de tombstone sont requis. Le systeme ne revele pas l'existence, le titre, le nombre ou la similarite d'une ressource interdite.

Les embeddings, scores, snippets, resumes, caches de reponse et historiques de conversation sont consideres sensibles au meme niveau que leur source. Une conversation ne sert jamais de memoire globale partagee. Toute relation inferee par l'IA conserve provenance, confiance et validation, sans devenir une ACL.

## 13. MCP utilisant un compte de service

Un compte de service casse l'hypothese selon laquelle le systeme source applique naturellement les droits de l'utilisateur. Il introduit notamment :

- lecture de ressources que l'utilisateur ne peut pas voir ;
- mutation avec des privileges superieurs ;
- attribution source au compte technique plutot qu'a l'auteur reel ;
- impossibilite de distinguer les utilisateurs dans certains audits fournisseurs ;
- fuite inter-projets/inter-espaces lors des recherches et de l'indexation ;
- confusion de mandataire et escalation via un identifiant de ressource devine ;
- difficultes de revocation immediate quand les droits utilisateur changent.

**Decision D-SVC-01 :** un MCP avec compte de service ne peut pas executer de mutation en production tant qu'une verification source fiable de l'autorisation de l'utilisateur, ressource par ressource et action par action, n'est pas demontree et testee. Si cette verification n'existe pas, la fonction est bloquee.

**Decision D-SVC-02 :** le compte de service ne doit jamais etre un administrateur global. Ses scopes, projets, spaces et fichiers sont limites au strict perimetre, avec comptes separes par environnement et, si necessaire, par tenant.

Pour la lecture, le meme principe s'applique : le service account peut recuperer des donnees uniquement apres calcul de l'intersection entre son acces et celui de l'utilisateur. Un filtrage fonde sur des roles recopies ou un cache stale n'est pas suffisant pour un contenu sensible.

**Recommandation R-SVC-01 :** privilegier une delegation OAuth individuelle de bout en bout. Si le MCP retenu ne la supporte pas, le traiter comme une exception d'architecture a accepter explicitement, avec reduction du perimetre ou remplacement du MCP.

## 14. Modele de menace

### 14.1 Actifs

- contenus Jira, Confluence, Figma et RAG ;
- permissions, identites et liaisons de comptes ;
- access/refresh tokens et secrets applicatifs ;
- Epics, User Stories, backlog et processus/CJM ;
- approbations, journal d'audit et preuves de synchronisation ;
- prompts, conversations et relations inferees.

### 14.2 Adversaires et hypotheses

Le modele couvre un utilisateur malveillant ou trop curieux, un contenu source compromis, un jeton vole, un navigateur compromis, un MCP mal configure ou compromis, une sortie LLM hallucinee/manipulee et un operateur interne abusif. Il suppose que le fournisseur d'identite, les API sources et le coffre de secrets fonctionnent selon leurs contrats ; leur compromission totale releve du plan de reponse a incident et de la revocation globale.

### 14.3 Menaces et controles

| Menace | Exemple | Controles principaux | Risque residuel |
|---|---|---|---|
| Usurpation | reutilisation d'une session ou d'un code OAuth | OIDC, PKCE, state/nonce, cookie securise, expiration | vol du poste utilisateur |
| Elevation de privileges | LLM choisit un autre compte/tenant | contexte signe, liaison serveur-side, revalidation source | MCP/source mal configure |
| Token replay/passthrough | jeton Jira envoye au MCP ou inversement | audience/resource, jetons distincts, coffre, rotation | bearer token vole avant expiration |
| Confused deputy | MCP appelle une API au nom du mauvais sujet | liaison des sujets, audience, policy engine, aucun endpoint libre | erreur d'association de compte |
| Prompt injection indirecte | ticket ordonne de supprimer une page | donnees/instructions separees, allowlist, schemas, HITL lie | influence sur qualite du contenu propose |
| Approbation falsifiee | texte source affiche un faux bouton | UI serveur, CSRF, hash, action a usage unique | poste/session compromis |
| Action modifiee apres accord | payload ou cible change | payload canonique immutable, hash et version | faiblesse cryptographique/implementation |
| Double creation | retry apres timeout | idempotence, outbox, reconciliation | fournisseur sans recherche fiable |
| TOCTOU | droit ou page change apres apercu | revalidation, ETag/version, fail closed | tres courte fenetre cote source |
| Fuite RAG inter-tenant | voisin vectoriel d'un autre projet | partition/filtre avant recherche, ACL par chunk | erreur d'ACL source ou d'ingestion |
| RAG poisoning | page hostile indexee | provenance, quarantaine, contenu non fiable | faux faits plausibles |
| Exfiltration HTML/Markdown | image distante encode des donnees | echappement, proxy/allowlist, CSP | lien volontairement ouvert par l'utilisateur |
| SSRF | outil accepte une base URL arbitraire | endpoints admin allowlistes, egress filtre | fournisseur compromis |
| MCP supply-chain | outil change de schema/comportement | version pinnee, hash schema, revue, kill switch | compromission sans changement visible |
| Repudiation | auteur nie une suppression | audit append-only, identite et hash d'approbation | compte utilisateur compromis |
| Denial of service/couts | boucle d'outils ou export massif | quotas, timeout, budget, profondeur max, circuit breaker | attaque distribuee |
| Menace interne | lecture de tokens/logs | coffre, RBAC, separation des devoirs, audit admin | administrateur privilegie compromis |

## 15. Exigences de securite testables

| ID | Exigence MVP |
|---|---|
| SEC-AUTH-01 | Toute requete utilisateur possede une session valide et un `tenant_id` reconstruit cote serveur. |
| SEC-AUTH-02 | Les flux OAuth utilisent code + PKCE, `state`, URI exacte et `nonce` pour OIDC. |
| SEC-AUTH-03 | Chaque MCP valide issuer, audience, expiration et scopes ; aucun token passthrough n'est possible. |
| SEC-TOOL-01 | Un outil absent, non versionne ou dont le schema differe de l'allowlist est refuse. |
| SEC-TOOL-02 | Les arguments hors schema, endpoints non autorises et identifiants de compte fournis par le LLM sont refuses. |
| SEC-APP-01 | Toute operation `CREATE`, `UPDATE` ou `DELETE` reste inexecutable sans approbation explicite valide. |
| SEC-APP-02 | Le payload execute est octet-semantiquement equivalent au payload canonique approuve. |
| SEC-APP-03 | Droits source et version de la cible sont revalides juste avant execution ; echec ferme sinon. |
| SEC-APP-04 | Approbation expiree, rejouee, d'un autre utilisateur/tenant ou modifiee est refusee. |
| SEC-IDEM-01 | Un retry ou timeout ne peut produire deux objets logiques ; les cas ambigus passent en reconciliation. |
| SEC-RAG-01 | Aucun chunk, score, titre, compte ou relation interdit ne peut apparaitre dans un resultat ou contexte LLM. |
| SEC-RAG-02 | Chaque noeud retourne par le graphe passe son propre controle d'acces. |
| SEC-LLM-01 | Une instruction dans Jira/Confluence/Figma/RAG ne peut ni approuver ni lancer directement un outil. |
| SEC-LLM-02 | Les sorties chat et apercus sont echappes et ne declenchent aucun chargement distant non autorise. |
| SEC-SEC-01 | Aucun secret ou jeton n'apparait dans les prompts, logs, traces, erreurs, RAG ou frontend. |
| SEC-AUD-01 | Toute mutation possede une trace complete, immutable et correlee ; sans audit, l'execution est bloquee. |
| SEC-SVC-01 | Un compte de service ne peut pas depasser l'intersection verifiee de ses droits et de ceux de l'utilisateur. |
| SEC-OPS-01 | Chaque MCP et outil de mutation dispose d'un kill switch, de quotas, timeout et alertes. |

## 16. Strategie de tests de securite

### 16.1 Tests automatises bloquant la CI

1. **Sessions/OAuth** : mauvais `state`, `nonce`, redirect URI, issuer, audience, signature, token expire ou code rejoue ; tous doivent etre refuses.
2. **Audience MCP** : presenter un jeton Jira MCP a Confluence MCP, un ID Token comme access token et un jeton aval au gateway ; tous doivent etre refuses.
3. **Token passthrough** : instrumenter le connecteur et verifier que le token MCP n'est jamais celui envoye a l'API source.
4. **Allowlist** : ajouter dynamiquement un outil, modifier son schema, utiliser un alias ou des champs supplementaires ; le gateway doit refuser.
5. **Validation** : fuzzing JSON Schema, tailles extremes, encodages, path traversal, URL/DNS/redirect SSRF et IDs d'un autre tenant.
6. **Approbation** : aucune mutation sans approbation ; payload change, mauvais utilisateur, mauvais tenant, expiration, rejeu, CSRF, double clic et modification apres approbation.
7. **TOCTOU** : retirer le droit ou modifier la ressource entre apercu et execution ; resultat `DENIED` ou `CONFLICT`, aucun effet source.
8. **Idempotence** : retries concurrents, timeout avant/apres reponse, crash du worker et livraison multiple de l'outbox ; un seul objet ou reconciliation manuelle.
9. **Isolation RAG** : corpus adversarial avec textes identiques dans deux tenants/projets ; aucune metadonnee ou similarite interdite ne fuite.
10. **Graphe** : noeud de depart autorise relie a un noeud interdit ; le voisin et les deductions revelant son existence sont absents.
11. **Injection** : instructions directes, indirectes, Unicode/invisibles, HTML/Markdown, contenu Figma cache, macros Confluence, ticket Jira et RAG empoisonne ; aucune approbation ou mutation n'est declenchee.
12. **Secrets** : scans des logs, traces, erreurs, snapshots, prompts et frontend avec canary tokens ; zero occurrence.
13. **Audit** : chaque mutation reconstitue proposition, controle, approbation, appel et resultat ; tentative de modification/suppression detectee.
14. **Compte de service** : le service voit une ressource que l'utilisateur ne voit pas ; lecture, RAG et mutation utilisateur doivent etre refusees.
15. **Transport MCP** : version non approuvee, en-tetes absents ou differents du corps, mauvaise correlation JSON-RPC, mauvais type de contenu, reponse trop grande et downgrade silencieux ; tous sont refuses.
16. **Profil lecture seule** : outil inconnu, schema modifie, annotation `readOnlyHint` mensongere, `use_figma`, outil Preview, `cloudId` ou fichier fourni par le LLM et resultat contenant une URL active ; aucun appel interdit ni telechargement secondaire ne se produit.

### 16.2 Tests d'integration et preproduction

- matrice reelle de roles Jira/Confluence/Figma : lecture seule, contributeur, administrateur projet/espace, aucun acces ;
- revocation du consentement OAuth et rotation de refresh token pendant une conversation ;
- indisponibilite de la source au moment de revalider : mutation bloquee ;
- test de charge des quotas et prevention des boucles d'outils ;
- compromission simulee d'un MCP et activation du kill switch ;
- restauration chiffree et verification que les grants revoques ne redeviennent pas actifs ;
- pentest des flux d'approbation, BOLA/IDOR, CSRF, SSRF et isolation multi-tenant ;
- red-team LLM/RAG avant pilote puis regulierement avec corpus Jira, Confluence et Figma representatif.

### 16.3 Critere de sortie Sprint 0

Le Sprint 0 securite est valide lorsque chaque exigence `SEC-*` a un proprietaire, un test automatisable ou une procedure explicite, et que les questions ouvertes bloquantes ci-dessous ont une date de decision. Aucun MCP de mutation n'est active avant cette validation.

## 17. Exploitation et reponse a incident

Prevoir des kill switches par tenant, serveur et outil, des quotas utilisateur, des limites de profondeur/nombre d'appels, des timeouts, des circuit breakers et des budgets LLM. Les anomalies suivantes alertent : refus d'audience, outils inconnus, volume de lectures inhabituel, injections repetees, approbations/rejets anormaux, changements de compte source, erreurs de revalidation et acces inter-tenant refuses.

La procedure d'incident doit permettre de :

1. couper un outil ou MCP sans arreter les fonctions de lecture saines ;
2. revoquer les grants et sessions affectes ;
3. isoler les chunks RAG suspects ;
4. identifier les actions via les correlations d'audit ;
5. reconcilier les mutations au resultat ambigu ;
6. notifier selon les obligations applicables ;
7. restaurer uniquement apres rotation et tests.

## 18. Decisions retenues

1. Gateway obligatoire et `default deny` pour tous les outils.
2. Identite utilisateur de bout en bout ; OIDC pour la plateforme et grants OAuth sources distincts.
3. Audience stricte, parametre `resource` et interdiction absolue du token passthrough.
4. Aucune mutation sans apercu canonique, approbation liee et revalidation source.
5. Idempotence serveur, controle de version et reconciliation des timeouts ambigus.
6. Audit append-only bloquant pour les mutations et coffre de secrets dedie.
7. Contenus externes et sorties LLM toujours non fiables.
8. Filtrage RAG avant recherche et ACL sur chaque noeud du graphe.
9. Mutations via compte de service bloquees sans preuve d'autorisation utilisateur fiable.
10. Pilote distant limite aux endpoints GA officiels Atlassian et Figma ; endpoint Atlassian Preview interdit.
11. Outils du pilote classes localement `READ` et inscrits dans les allowlists de la section 5.4 ; toute autre capacite est refusee.
12. OAuth interactif par utilisateur, bindings source opaques et identifiants de site/fichier reconstruits cote serveur.
13. MCP `2026-07-28` est la reference normative ; outils et schemas sont epingles par paquet de contrat.
14. Aucun runner ou adaptateur de mutation n'est active pendant le pilote lecture seule.

## 19. Recommandations a confirmer

1. Tokens courts, rotation des refresh tokens et preuve de possession si supportee.
2. Suppression reversible par defaut et authentification renforcee pour permanent/batch.
3. Partitions RAG par tenant et, pour les donnees tres sensibles, par domaine de permission.
4. Separation du composant qui lit le contenu hostile et du composant habilite a proposer des outils.
5. mTLS ou identites de workload entre services internes ; egress reseau strict par MCP.
6. Audit WORM/chainage cryptographique et coffre avec KMS/HSM.
7. Webhooks de permissions/suppression completes par verification source a TTL court.
8. Une compatibilite MCP anterieure a `2026-07-28` isolee dans un paquet de contrat par serveur, uniquement si la qualification fournisseur l'exige.

## 20. Qualification et questions ouvertes

Les faits suivants sont qualifies pour le pilote :

1. Jira et Confluence sont des sites Atlassian Cloud, sur deux hotes distincts.
2. Le serveur retenu est Atlassian Rovo MCP GA pour Jira et Confluence, et Figma Remote MCP pour Figma.
3. La delegation est OAuth par utilisateur ; les API tokens et comptes partages ne sont pas un mode produit acceptable.
4. Le pilote est strictement en lecture seule ; la capacite d'ecriture Figma reste hors perimetre.

Les points suivants restent bloquants avant un GO reel :

1. **Bloquante lecture :** quel fournisseur OIDC authentifie les utilisateurs de la plateforme et quel domaine de callback est enregistre ?
2. **Bloquante lecture :** les deux `cloudId` Atlassian sont-ils visibles par le meme utilisateur pilote et les permissions admin `Read`/`Search` autorisees avec `Write` bloque ?
3. **Bloquante lecture :** le client backend Project Knowledge Assistant est-il admis par Figma pour utiliser son serveur distant ?
4. **Bloquante lecture :** quelles versions MCP sont effectivement negociees par chaque serveur et quelles sont les empreintes revues de leurs schemas reels ?
5. Quelles durees de session, de grant, de cache de permissions, d'audit et de contenu RAG sont retenues au-dela des limites techniques du pilote ?
6. Quelles exigences de residence, classification, chiffrement et suppression des donnees s'appliquent ?
7. Quels volumes, SLA, RTO/RPO et contraintes de cout Groq/embeddings sont attendus ?
8. L'index RAG est-il partage dans un tenant avec ACL dynamiques ou partitionne par projet/espace ?
9. Quelles donnees peuvent etre envoyees a Groq et au fournisseur d'embeddings selon les contrats de confidentialite ?
10. Pour une phase de mutation ulterieure, quels mecanismes source existent pour version/ETag, idempotence, corbeille et permission-check par ressource ?
11. Pour une phase de mutation ulterieure, l'approbateur doit-il toujours etre l'auteur ou certaines actions exigent-elles une separation des devoirs ?

### 20.1 Conditions avant GO reel du pilote

1. Remplacer l'identite `dev_headers` par OIDC, session serveur et protection CSRF.
2. Implementer les flux OAuth utilisateur, le broker de grants opaques et la revocation sans exposer les jetons.
3. Enregistrer le domaine/callback du client, confirmer les deux bindings Atlassian et bloquer `Write` dans l'administration Atlassian.
4. Obtenir l'admission Figma et lier explicitement le compte, le fichier et le noeud de test.
5. Executer `tools/list` authentifie en sandbox, revoir les schemas, construire les paquets de contrat et en approuver les empreintes.
6. Demonstrer les tests de transport, default deny, schema change, SSRF, OAuth mix-up, isolation tenant, revocation, timeout, resultat hostile, audit et absence de secret.
7. Conserver les kill switches coupes par defaut, les activer serveur par serveur et tenant par tenant apres verdict QA et revue Securite.

## 21. References normatives et guides

- [MCP Authorization, specification 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [MCP Streamable HTTP, specification 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- [MCP Tools, specification 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [MCP Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)
- [Atlassian Rovo MCP overview](https://developer.atlassian.com/cloud/rovo-mcp/)
- [Atlassian Rovo MCP supported tools](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/supported-tools/)
- [Atlassian Rovo MCP permissions](https://support.atlassian.com/security-and-access-policies/docs/Configure-Atlassian-Rovo-MCP-server-permission/)
- [Atlassian Rovo MCP audit](https://support.atlassian.com/security-and-access-policies/docs/monitor-atlassian-rovo-mcp-server-activity/)
- [Figma Remote MCP installation](https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/)
- [Figma MCP tools](https://developers.figma.com/docs/figma-mcp-server/tools-and-prompts/)
- [Figma MCP rate limits and access](https://developers.figma.com/docs/figma-mcp-server/rate-limits-access/)
- [RFC 9700 - Best Current Practice for OAuth 2.0 Security](https://www.rfc-editor.org/rfc/rfc9700.html)
- [RFC 8707 - Resource Indicators for OAuth 2.0](https://www.rfc-editor.org/rfc/rfc8707.html)
- [RFC 9728 - OAuth 2.0 Protected Resource Metadata](https://www.rfc-editor.org/rfc/rfc9728.html)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0-final.html)
- [OWASP LLM Prompt Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
- [OWASP LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)

MCP `2026-07-28` est une version finale, et non une release candidate. Sa compatibilite effective avec chaque endpoint fournisseur et les schemas observes reste qualifiee et epinglee par paquet de contrat avant activation.
