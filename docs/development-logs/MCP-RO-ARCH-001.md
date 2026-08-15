# MCP-RO-ARCH-001 — Connecteurs MCP en lecture seule

## Exécution

- Déclencheur : ordre explicite dans le chat
- Taille : L
- Branche : `feature/mcp-readonly-connectors`
- Commit fonctionnel : `4a7befa`
- Tâches associées : `MCP-RO-ARCH-001`, `MCP-RO-BE-001`, `MCP-RO-SEC-002`, `MCP-RO-QA-002`
- Statut : `Ready for Review` — Atlassian qualifié contre le serveur réel le 2026-08-13 ;
  Figma reste non qualifié, bloqué par l'admission au catalogue

## Objectif et résultat

Le backend expose un chemin de lecture MCP complet et fermé par défaut vers Atlassian
(Jira, Confluence) et Figma. Une lecture n'aboutit que si elle traverse, dans cet ordre :
allowlist locale d'outils, validation JSON-Schema des arguments, vérification du hash
SHA-256 du schéma distant, liaison serveur des identifiants sensibles, appel MCP borné,
normalisation du résultat avec provenance, puis audit.

Aucune mutation externe n'est activée. Le profil pilote est décrit et figé dans
`docs/security/mcp-security-design.md` §5.4.

Points structurants de l'implémentation :

- **Registre de contrats** (`registry.py`) : les outils autorisés sont des constantes, avec
  schéma d'entrée local, hash canonique du schéma fournisseur et classe d'action `READ`.
  Un outil absent du registre est refusé sans appel réseau.
- **Liaison serveur** : `cloudId`, `fileKey` et `nodeId` proviennent exclusivement du binding
  serveur. Un identifiant injecté dans les arguments ou le prompt est rejeté — couvert par des
  tests paramétrés sur `cloudId`, `endpoint`, `tenant_id`, `user_id`, `fileKey`, `nodeId`.
- **Transport** (`adapters/remote.py`) : Streamable HTTP, endpoints constants en HTTPS sans
  userinfo ni query string, redirections désactivées, résolution DNS refusant les adresses
  privées, loopback, link-local et metadata. Versions protocolaires approuvées vérifiées, pas
  de downgrade silencieux.
- **Limites** : 3 s de connexion, 30 s par appel, 2 Mio texte/structuré, 8 Mio image,
  3 appels par tour, aucun retry. Un dépassement est refusé, jamais tronqué en silence.
- **Non-fuite de secret** : le jeton porteur est recherché dans les fragments texte et binaires
  de la réponse ; une réponse qui le contient est rejetée.
- **Audit fail-closed** : la trace est requise avant l'appel. Une panne d'audit bloque la lecture.
  Elle enregistre hash des arguments, `binding_fingerprint`, hash de schéma, décision, durée et
  taille — jamais le payload, les requêtes JQL/CQL ni les en-têtes d'autorisation.

## Rôles mobilisés

- Architecte / Tech Lead : cadrage, contrats partagés, branche et intégration
- MCP / IAM / Sécurité : profil pilote, allowlists, modèle de menace, SSRF, secrets, audit
- Backend : registre, workflow de lecture, adaptateurs, API et tests
- QA / Test Automation : campagne hermétique sur les refus et les limites

## Fichiers et modules principaux

- `backend/app/mcp/registry.py` : contrats d'outils, schémas locaux et hachage canonique
- `backend/app/mcp/read_workflow.py` : autorisation, liaison, appel, normalisation, audit
- `backend/app/mcp/adapters/remote.py` : transport Streamable HTTP et contrôles réseau
- `backend/app/mcp/adapters/grants.py` : courtier de jetons délégués, broker de développement
- `backend/app/mcp/api.py`, `domain.py`, `errors.py`, `ports.py`
- `backend/app/core/config.py`, `backend/app/bootstrap.py`, `backend/app/main.py`
- `backend/tests/test_mcp_*.py`
- `docs/security/mcp-security-design.md`
- `infra/compose.yaml`, `infra/.env.example`, `infra/README.md`

## Vérifications et preuves

Campagne rejouée le 2026-08-12 sur le commit `4a7befa` :

- Pytest complet : `88 passed, 5 skipped`
- Les 5 tests ignorés sont ceux de `test_postgres_integration.py`, désactivés hors PostgreSQL réel
- Pytest sur les seuls modules MCP : `70 passed` pour 1 676 lignes de test
- Ruff sur `app`, `tests` et `migrations` : `All checks passed!`
- Routeur MCP monté dans `app/main.py`
- Aucun `TODO`, `FIXME` ni `NotImplementedError` dans `app/mcp/`

## Campagne réelle Atlassian — 2026-08-13

Les onze outils Atlassian épinglés ont été exécutés contre `https://mcp.atlassian.com/v1/mcp`
depuis le conteneur `api`, avec un jeton porteur délégué en fichier de développement. Tous
répondent. Un enchaînement réel a été vérifié : espace `98309` → page `98421` → corps et
descendants. La suite hermétique reste inchangée et fait toujours foi en CI ; cette campagne
la complète, elle ne la remplace pas.

Cinq constats ont forcé des correctifs, chacun masquant le suivant :

- **Portée de scope anyio.** `read_workflow.py` fermait un `fail_after` alors que le groupe de
  tâches ouvert par `Client.__aenter__()` vivait encore, d'où un `RuntimeError` remonté en 500.
  Le transport entre et sort désormais du client dans le même scope. Corollaire découvert au
  passage : ce `RuntimeError` échappait au `except MCPReadError` et **sortait sans événement
  d'audit**, contredisant l'invariant fail-closed. Un `except Exception` terminal referme le
  trou. Preuve en base : un unique événement `MCP_READ_AUTHORIZED` orphelin, corrélation
  `455412031f52488db7daebaaf24cd1fe:1`, antérieur au correctif ; toutes les lectures
  postérieures ont leur événement de clôture.
- **Version protocolaire.** Le serveur négocie `2025-11-25`, absente de l'allowlist. Vérifié
  empiriquement : il descend à ce que le client demande (2025-06-18, 2025-03-26 et 2024-11-05
  ont tous été acceptés). L'épinglage est donc un contrôle réel — toute entrée ajoutée élargit
  ce qu'un fournisseur peut imposer. `2025-11-25` ajoutée seule, politique passée en `r2`.
- **Dérive de schéma.** Les schémas fournisseur doivent reproduire le fournisseur octet pour
  octet. `_EMPTY` portait un `additionalProperties: false` que nous avions inventé, d'où un
  refus sur les outils sans argument ; `_PROVIDER_EMPTY` les sépare désormais du contrat public.
  Cinq contrats réalignés. Deux d'entre eux exposaient publiquement des paramètres qu'Atlassian
  n'accepte plus (`depth`, `cursor`, `sort`, `descriptionFormat`, `includeIcon`) : un appelant
  passait notre validation puis se faisait rejeter à distance.
- **Sémantique du cloudId.** Atlassian émet **un cloudId par site**, couvrant Jira et Confluence,
  et non un par produit. La contrainte de distinction inscrite dans `config.py` interdisait donc
  la configuration correcte ; elle est supprimée. Les deux variables restent séparées et chacune
  reste obligatoire quand son produit est activé.
- **JQL non bornée refusée.** Atlassian exige une restriction de recherche ; `order by created
  DESC` seul est rejeté, `created >= -365d order by created DESC` passe. Comportement fournisseur,
  pas défaut du backend.

## Limites connues et blocages

- **Figma n'est pas qualifiable en l'état, et le blocage est administratif.** Voir
  « Figma : blocage au catalogue » plus bas. La suite reste hermétique pour ce fournisseur et
  les hash de schéma inscrits au registre restent à confirmer contre le serveur de production.
- **Classification trompeuse de deux erreurs de transport.** `httpx2.ConnectTimeout` n'hérite
  pas du `TimeoutError` natif, et un 401 fournisseur n'est pas distingué : les deux remontent en
  `MCP_TRANSPORT_FAILURE` (502) au lieu de `MCPCallTimeout` (504) et `MCPGrantUnavailable` (503).
  Le diagnostic oriente donc à tort vers un renouvellement de jeton. Non corrigé.
- **Budget de connexion de 3 s trop court** pour une sortie réelle depuis un poste de
  développement : des `ConnectTimeout` intermittents ont été observés sur des sondes isolées
  alors que le jeton et les liaisons étaient valides. Une sonde qui échoue seule pendant que les
  autres passent ne signale pas une expiration de jeton.
- **Le jeton de développement expirait sans être rafraîchi**, le courtier relisant un fichier
  statique. Corrigé le 2026-08-14, voir « Jetons auto-renouvelés » plus bas : la durée réelle
  est d'environ 8 h, et le courtier échange désormais lui-même le grant. Un compte de service
  reste nécessaire pour un usage hors développement.
- **Blocage externe Figma** : le serveur MCP Figma n'admet que les clients de son catalogue.
  L'admission du backend est un prérequis hors de notre contrôle avant tout test réel.
- **Identité encore en mode développement** : `app/core/identity.py:28` porte toujours le
  `TODO(IAM)` sur le remplacement des en-têtes de développement par un OIDC vérifié. Le chemin
  de lecture MCP hérite de cette limite ; elle sort du périmètre de ce chantier mais conditionne
  tout usage hors poste de développement.
- **Aucune mutation MCP n'est active**, conformément au principe non négociable. `ApprovedMutationRunner`
  existe dans `app/agent/mutation_workflow.py` mais n'est instancié nulle part.

## Suite

1. Faire rendre un verdict QA indépendant sur la campagne Atlassian avant de passer les tâches
   `MCP-RO-*` en `Done`.
2. Corriger la classification des deux erreurs de transport et relever le budget de connexion.
3. Obtenir l'admission du client Figma, puis rejouer la campagne pour ce fournisseur.
4. Indexer Confluence dans pgvector en s'appuyant sur `resource_reference` pour les citations.

## Citations — 2026-08-13

`resource_reference` est désormais renseigné, par dérivation et non par observation : le
contrat déclare un chemin portant un seul placeholder nommant un argument public **requis**,
rempli après validation JSON-Schema puis percent-encodé sans caractère sûr. Aucune donnée
issue de la réponse fournisseur n'y entre, donc la surface d'injection reste nulle et un
serveur compromis ne peut pas rediriger une citation. `__post_init__` refuse un chemin citant
un argument optionnel, qui produirait des citations nulles au hasard des appels.

Quatre contrats en portent un : `getJiraIssue` et `getJiraIssueRemoteIssueLinks` vers
`/browse/{issueIdOrKey}`, `getConfluencePage` et `getConfluencePageDescendants` vers
`/wiki/pages/{pageId}`. Les outils de recherche et de liste n'adressent pas une ressource
unique et retournent `null`. `source_complete` reste `false` partout.

## Deux sites Atlassian — 2026-08-14

`getAccessibleAtlassianResources` ne liste que les sites couverts par **le jeton présenté**.
Un appel unique n'est donc jamais la preuve qu'un site n'existe pas. Le 2026-08-13, ce
raisonnement a été fait à l'envers : le jeton était scopé sur le site Confluence, l'outil n'a
retourné que celui-ci, et `JIRA_SOURCE_ORIGIN` a été « corrigé » vers cet hôte. C'était faux.

Le déploiement comporte **deux sites distincts**, chacun portant un produit, chacun confirmé
par un jeton scopé sur lui :

| Site | Produit | cloudId |
| --- | --- | --- |
| `https://andrianalyfanny-1786296714755.atlassian.net` | Jira | `c3f33a07-373a-4c4c-94ea-08d4fc750651` |
| `https://andrianalyfanny.atlassian.net` | Confluence | `a761589f-69b8-4373-9c30-7561c2d45a39` |

`JIRA_SOURCE_ORIGIN` est rétabli à sa valeur d'origine et `PKA_MCP_ATLASSIAN_JIRA_CLOUD_ID`
corrigé : il portait le cloudId Confluence, donc toutes les lectures Jira du 2026-08-13
interrogeaient le mauvais site. Elles répondaient `200` avec une liste vide, ce que le smoke
test compte comme un succès — il qualifie la connexion, jamais la pertinence du contenu.

Conséquence structurelle : **un jeton délégué ne couvre qu'un seul site**, alors que le
courtier de grants indexait par fournisseur. Jira et Confluence ne pouvaient donc pas être lus
dans la même configuration ; activer l'un faisait répondre 401 à l'autre. Corrigé le même jour :
le courtier indexe désormais par `(fournisseur, liaison)`, chaque combinaison étant enregistrée
explicitement à l'amorçage. Aucun repli à l'exécution : une liaison non enregistrée échoue en
`MCP_GRANT_UNAVAILABLE` plutôt que d'emprunter le jeton d'une autre, ce qui reviendrait à
présenter la crédentielle d'un site à un appel visant l'autre.

Preuve des deux produits simultanés : Jira `KAN-1/2/3` sur `…-1786296714755`, et l'espace
Confluence `DL` sur `andrianalyfanny`, lus dans la même configuration, avec deux
`binding_fingerprint` distincts et deux `source_origin` distincts.

Preuve de lecture réelle après correction : `KAN-2` du projet `KAN` (« My Software Team »),
statut « En cours », citation `https://andrianalyfanny-1786296714755.atlassian.net/browse/KAN-2`,
corrélation `963c710d26ea4fcab3b0d9a9bfb81bec:1`.

## Jetons auto-renouvelés — 2026-08-14

Un jeton d'accès Atlassian vit environ 8 h (`expires_in: 28320`), pas une heure comme
l'annonçait le smoke test. Sur un montage à jeton statique, cela impose une ré-autorisation
manuelle à peu près chaque jour ouvré — et chaque expiration se présentait comme un
`MCP_TRANSPORT_FAILURE`, ce qui a envoyé le diagnostic vers le réseau deux fois dans la
même journée.

La cause n'était pas la durée de vie mais l'absence de renouvellement : le courtier lisait un
fichier et rien d'autre, ignorant qu'un `refresh_token` existait. Le serveur MCP Atlassian
publie pourtant tout ce qu'il faut à
`/.well-known/oauth-authorization-server` : `token_endpoint` sur `cf.mcp.atlassian.com/v1/token`,
`grant_types_supported` incluant `refresh_token`, et `token_endpoint_auth_method: none` —
client public, donc aucun secret client à détenir.

`RenewableCredentialsFile` échange donc lui-même un grant expiré. Trois points non évidents :

- **Le `token_endpoint` est épinglé dans le registre, jamais lu depuis le document.** Il suffirait
  de falsifier le fichier une fois pour rediriger le `refresh_token` vers un tiers.
- **Atlassian fait tourner le `refresh_token` à chaque échange.** Le document est donc réécrit,
  atomiquement (fichier voisin puis `os.replace`) : perdre le nouveau jeton ramènerait
  définitivement à la ré-autorisation manuelle. Un verrou sérialise les renouvellements, deux
  échanges concurrents révoquant le perdant.
- **Un secret Compose `file:` ne convient pas** : il est copié en lecture seule à la création du
  conteneur. D'où un montage lecture-écriture dans `compose.atlassian-oauth.yaml`, qui supprime
  aussi le `--force-recreate` après rotation.

Un échec de renouvellement remonte en `MCP_GRANT_UNAVAILABLE` (503), jamais avec le corps de
la réponse : celui-ci contient le code d'erreur du fournisseur et parfois le grant lui-même.

Reste ouvert : `ConnectTimeout` et un 401 fournisseur sont toujours classés
`MCP_TRANSPORT_FAILURE` (502) au lieu de 504 et 503, et `CONNECT_TIMEOUT_SECONDS = 3.0`
produit des échecs isolés au premier appel.

Défaut de conception constaté à la mise en service : le renouvellement ne se déclenche que
sur l'horloge, jamais sur un refus. Un jeton **révoqué** avant son expiration — ce que fait
Atlassian quand le même client est ré-autorisé — reste présenté jusqu'à sa date théorique, et
échoue en boucle. Un 401 devrait déclencher un échange puis une seule reprise.

## Retour au mono-site — 2026-08-14

Un espace Jira a été créé sur `andrianalyfanny`, qui porte déjà Confluence. Un seul site, donc
un seul cloudId, un seul jeton, et les surcharges par liaison redeviennent inutiles : le
document de credentials du fournisseur sert les trois liaisons par défaut. `JIRA_SOURCE_ORIGIN`
suit et vaut désormais le même hôte que Confluence.

Les tickets `KAN-1/2/3` (« My Software Team ») restent sur `…-1786296714755` et sortent du
périmètre lisible ; le `KAN` du nouveau site (« Mon espace Kanban ») est vide.

Deux erreurs de méthode dans cette séance, de la même famille que celle du 2026-08-13 :

- Un diagnostic « mauvais site » a été prononcé alors que la mesure passait par l'**ancien
  code** — le conteneur n'avait pas été reconstruit, et le courtier statique répondait à la
  place du document. Le Dockerfile embarque les sources : `--force-recreate` ne suffit jamais,
  il faut `--build`.
- Là encore, `getAccessibleAtlassianResources` a été lu comme une propriété du site alors
  qu'il est une propriété **du jeton présenté**.

## Figma : blocage au catalogue — 2026-08-14

Tentative de connexion au serveur MCP Figma. Elle échoue avant l'écran de consentement :
`mcp-remote` reçoit **403 Forbidden** sur `https://api.figma.com/v1/oauth/mcp/register`, en
texte brut et non en erreur OAuth, ce qui fait d'ailleurs échouer son analyseur.

La documentation de Figma donne la raison sans ambiguïté : seuls les clients inscrits à son
catalogue — VS Code, Cursor, Claude Code, Codex, Xcode — peuvent se connecter. Le 403 sur
l'enregistrement dynamique *est* le mécanisme d'application de cette règle.

Aucun contournement n'existe côté dépôt. Une application OAuth déclarée à la main ne résout
rien : la console d'applications Figma ne délivre pas la portée `mcp:connect`, seule portée
annoncée par le serveur. La voie unique est l'admission au catalogue, via la liste d'attente
liée depuis la page d'installation du serveur distant.

Ce qui a quand même été livré, et qui reste valable :

- **Le renouvellement gère désormais les clients confidentiels.** Les métadonnées de Figma
  n'annoncent que `client_secret_basic` / `client_secret_post`, jamais `none` — contrairement à
  Atlassian. Le `client_secret` est donc transmis quand le document en porte un, et omis
  sinon ; l'envoyer à vide serait refusé par Atlassian. Deux tests couvrent les deux cas.
- `infra/compose.figma.yaml`, la configuration `PKA_MCP_FIGMA_CREDENTIALS_FILE` et le câblage
  d'amorçage sont en place et testés, prêts pour le jour de l'admission.
- Le script d'import est devenu générique (`mcp_credentials_import.py`) et reprend le
  `client_secret` quand `mcp-remote` en a reçu un.

Non vérifié, et non vérifiable tant que le blocage tient : les hash de schéma des cinq outils
Figma, et l'appartenance du `fileKey` épinglé `Ie3SsqL1KetjinTDHcNm2D` au compte courant.

## Figma par l'API REST — 2026-08-14

Le blocage du catalogue étant administratif et sans recours, Figma est désormais lu par son
**API REST** plutôt que par son serveur MCP. Deux options avaient été mises en balance.

La première — héberger notre propre serveur MCP, adossé à la même API REST — avait un attrait
réel : le serveur aurait publié ses propres schémas, redonnant du sens au contrôle de dérive,
et aurait été réutilisable depuis Cursor ou VS Code. Elle a été écartée pour une raison
dirimante : depuis le backend, un serveur interne dans Docker est indiscernable d'une SSRF. Les
trois invariants du transport — HTTPS validé à l'import, adresse `is_global`, port fixé à 443 —
l'auraient refusé en `MCP_DNS_REJECTED`, et l'atteindre aurait exigé d'inscrire dans le dépôt
l'endroit précis où le projet désactive sa propre protection. Coût certain, bénéfice hypothétique.

La seconde a été retenue : `https://api.figma.com` est un hôte public en HTTPS sur 443, donc
**aucun invariant n'a été relâché**. Le pipeline — allowlist, validation JSON-Schema, injection
serveur de la liaison, bornes de taille, provenance, audit fail-closed — est resté inchangé,
parce qu'il vit au-dessus du transport et non dedans.

Ce que la bascule a coûté et rapporté :

- **Lecture seule par construction, pas seulement par politique.** L'API REST de Figma n'expose
  aucun point d'entrée qui crée ou modifie un nœud ; créer une frame demande l'API Plugin, qui
  s'exécute dans l'éditeur. L'invariant du lot coïncide avec ce que le fournisseur autorise.
- **Le contrôle de dérive devient tautologique** — les deux schémas comparés sont les nôtres. Il
  n'a pas été retiré pour autant : l'adaptateur publie son manifeste, le registre déclare ses
  contrats, les deux sont écrits séparément, et modifier l'un sans l'autre fait échouer la
  lecture au lieu de passer en silence. Un test l'atteste.
- **La version de protocole ne ment pas.** Une lecture REST ne traverse aucune session MCP,
  l'étiqueter `2026-07-28` aurait mis une fausse affirmation dans chaque enregistrement de
  provenance. Le marqueur `figma-rest-v1` est délibérément absent de
  `APPROVED_REMOTE_PROTOCOL_VERSIONS` : un serveur distant qui l'annoncerait serait refusé.
- **`nodeId` devient un argument public.** Seul le `fileKey` reste injecté côté serveur. Un
  identifiant de nœud ne désigne qu'un emplacement *dans* le fichier épinglé : l'honorer ne
  coûte rien, alors qu'un `fileKey` fourni par l'appelant transformerait un document approuvé
  en n'importe quel document que le jeton peut atteindre.
- **Deux erreurs de taxonomie signalées plus tôt sont corrigées sur ce transport** : un 401/403
  remonte en `MCP_GRANT_UNAVAILABLE` et non en échec réseau, et un dépassement de délai remonte
  en `MCP_CALL_TIMEOUT`. L'adaptateur MCP distant garde ses défauts, non traités ici.

Les gardes de transport communs aux deux adaptateurs — endpoint fixe, adresse publique, bornes
de réponse — ont été extraits dans `app/mcp/adapters/http_guard.py`. Deux copies d'un contrôle
d'adresse, c'est deux endroits à affaiblir, et le second est celui que personne ne relit.

`renderFigmaNode` renvoie l'URL produite par Figma sans la suivre : récupérer une destination
nommée par une réponse est précisément la forme que ce transport existe pour refuser.

Les cinq contrats du serveur MCP distant ont été retirés du registre. Les conserver aurait laissé
dans l'allowlist — donc dans la surface de sécurité — cinq outils définitivement injoignables.

Reste non vérifié : l'appartenance du `fileKey` épinglé au compte courant, et donc toute lecture
réelle. Rien n'a encore été lu dans Figma.

## Fournisseur LLM : Groq — 2026-08-15

Le premier consommateur des lectures MCP est un modèle. L'adaptateur qui l'appelle est livré ;
rien ne le câble encore, faute de boucle d'orchestration à alimenter.

### Choix du fournisseur et du modèle

Groq a été retenu pour le développement, sur trois critères : palier gratuit suffisant pour les
dizaines d'itérations qu'exige la mise au point d'une boucle agentique, débit élevé qui rend le
cycle supportable, et **API compatible OpenAI** — donc un seul adaptateur couvre Groq et OpenAI,
et le changement de fournisseur devient une variable d'environnement plutôt qu'un module.

Groq **ne propose aucun modèle d'embedding**. La question du fournisseur d'embeddings, laissée
ouverte pour l'étape d'indexation Confluence, n'est donc pas résolue par ce choix : elle est
tranchée séparément par `EMBEDDING_PROVIDER=local` avec `BAAI/bge-m3`, qui coûte zéro euro.

Le modèle est `qwen/qwen3.6-27b`. C'est le plus performant du catalogue Groq en raisonnement, ce
qui correspond au profil de la tâche : choisir le bon outil MCP et composer ses arguments. Trois
propriétés en découlent, toutes structurantes :

- **Sortie plafonnée à 16 384 tokens** contre 65 536 pour `gpt-oss-120b`. L'adaptateur borne la
  demande à cette valeur.
- **Modèle en preview** chez Groq : évaluation seulement, aucune garantie de disponibilité. À
  rebasculer sur un modèle de production avant une démonstration.
- **Vision native.** `renderFigmaNode` renvoie une URL d'image sans la suivre ; un modèle capable
  de lire une image ouvre la description de maquette. La suivre serait une requête sortante vers
  un CDN qu'aucun garde ne couvre aujourd'hui — décision de sécurité à part entière, non prise.

### Ce que l'adaptateur fixe

**L'endpoint est épinglé dans le module, validé à l'import, et absent de la configuration.** Une
destination que la configuration peut déplacer est une destination qu'un fichier d'environnement
modifié peut pointer ailleurs — en emportant la clé API dès la première requête. Un test échoue
si un champ de réglage évoquant une URL, un hôte ou une origine réapparaît dans `Settings`.

Les variables `GROQ_*` sont devenues `PKA_LLM_GROQ_*`. `Settings` ne lit que le préfixe `PKA_` :
les anciennes étaient injectées par Compose et lues par personne. La configuration paraissait
active alors qu'elle ne l'était pas.

**Tout ce qui revient est traité comme non fiable** : corps borné à 2 Mio avant bufferisation,
arguments d'outil parsés et refusés s'ils ne sont pas un objet, nom d'outil vérifié contre la
liste réellement proposée, classe d'action imposée à `READ` et jamais lue dans la réponse. Un
modèle qui renvoie `createJiraIssue` ressort en `READ`, et le registre le refuse ensuite.

Le garde de taille de `http_guard.py` devient paramétrable. Les transports MCP conservent leur
plafond de 12 Mio ; une complétion bornée à 16 384 tokens n'a aucune raison d'en obtenir autant.

`LLMProvider.generate` passe en `async` : un appel bloquant dans la boucle d'orchestration
gèlerait l'event loop le temps d'une inférence.

### Limites constatées en réel

Quatre problèmes que les tests unitaires ne pouvaient pas révéler, tous trouvés par sonde contre
`api.groq.com` :

- **Le palier gratuit plafonne à 8 000 tokens par minute, et le budget demandé compte** qu'il
  soit consommé ou non. L'adaptateur demandait 16 384 tokens à chaque appel : chaque requête
  dépassait la limite à elle seule. Le plafond devait être une borne, pas une quantité imposée ;
  `max_completion_tokens` est désormais demandé par requête, défaut 2 048.
- **Groq répond 413 pour ce cas**, en l'étiquetant `rate_limit_exceeded`. Attendre n'y change
  rien : il faut envoyer moins. `LLM_REQUEST_TOO_LARGE` est distinct de `LLM_RATE_LIMITED`.
  C'est la quatrième erreur de taxonomie du chantier et la troisième portant sur un quota ; le
  motif est constant, un fournisseur qui répond correctement se fait classer comme une panne.
- **Le modèle écrivait son raisonnement en clair dans la réponse**, entre balises `<think>`. Le
  texte destiné à l'utilisateur n'était pas la réponse, et le cheminement aurait fini dans une
  citation rendue. `reasoning_format: "parsed"` l'isole, et `_text_of` retire les balises par
  précaution — honorer le paramètre est un choix du modèle, et le modèle est configurable.
- **Le raisonnement consomme le budget de complétion.** Sur un modèle de raisonnement,
  `max_completion_tokens` couvre la réflexion *et* la réponse ; trop bas, la réflexion épuise le
  budget avant que la réponse commence, et `finish_reason: "length"` remonte en échec.

Conséquence à retenir pour la boucle : 8 000 tokens par minute est très serré pour un cycle
agentique qui réinjecte le contenu Jira ou Confluence à chaque tour. Trois étapes avec 5 000
tokens de contexte dépassent la fenêtre. À mesurer quand la boucle existera.

### Vérification indépendante — 2026-08-15

Le critère d'acceptation « QA et MCP/Sécurité rendent un verdict indépendant », ouvert depuis le
début du lot, est fermé sur ce périmètre. Deux agents ont audité le commit sans l'avoir écrit.

**QA : conforme avec réserves.** Chiffres reproduits indépendamment. Deux trous relevés : une
assertion faible dans le test d'épinglage — une liste de noms devinés plutôt qu'une propriété —
et cinq bornes déclarées mais non exercées, dont `MAX_TEXT_CHARACTERS`, qui est un chemin
distinct du plafond d'octets.

**Sécurité : approuvé sous réserve.** Épinglage vérifié jusqu'aux redirections et au proxy, clé
non divulguée y compris dans la chaîne d'exception, bornage confirmé antérieur à la
bufferisation par lecture de la source de `httpx2`, et **aucune régression** des transports MCP
après extraction du garde. Un défaut réel : `json.loads` lève `RecursionError`, qui n'est pas une
`ValueError` et échappait donc à la taxonomie fail-closed — atteignable depuis un contenu que le
modèle relaie. Trois écarts commentaire/code, dont un commentaire affirmant que
`allowed_tool_names` était appliqué alors qu'aucun code ne le lisait.

Tous ces constats sont corrigés. Le point le plus instructif est le dernier : un commentaire
rassurant sur un contrôle absent est plus dangereux que pas de commentaire du tout, et c'est
exactement ce que l'audit avait pour consigne de traquer.

**Réserve maintenue, non levée :** ne pas câbler l'adaptateur dans une boucle d'orchestration
tant qu'un audit d'appel LLM — tenant, utilisateur, corrélation — n'est pas livré. `context` est
aujourd'hui accepté et inutilisé. L'audit vérifiable est un non-négociable du projet.

**Limite transversale identifiée par les deux audits :** le contrôle DNS est un TOCTOU. La
résolution de validation et celle de la connexion sont distinctes, donc un rebinding passe entre
les deux. Le contrôle reste utile — il échoue vite sur une résolution manifestement fausse — mais
la vraie liaison est la validation TLS du certificat. Le schéma est identique dans `remote.py` et
`figma_rest.py` : à traiter comme une décision d'architecture sur les trois adaptateurs, pas
comme un correctif Groq isolé.

### Suite immédiate

La boucle d'orchestration, sur `feature/agent-orchestration`. Groq et l'orchestration dépassent
le périmètre de `feature/mcp-readonly-connectors`, dont le nom ne les couvre plus. Le commit
Groq reste dans l'historique de la branche MCP : elle est publiée, et la réécrire pour corriger
le périmètre d'un seul commit coûterait plus que ça ne rapporte.

## Outillage

`scripts/mcp-smoke.sh` sonde les trois surfaces — identité seule, puis Jira et Confluence qui
exercent en plus l'injection du cloudId — et extrait `detail.code`, seul champ qui discrimine les
six causes regroupées sous 502.

`scripts/mcp_credentials_import.py` construit un document de credentials à partir du cache
de `mcp-remote`, sans afficher ni faire transiter la moindre valeur par un copier-coller ou par
l'historique du shell. À rejouer une fois par site, et seulement si le `refresh_token` est révoqué.

Piège persistant du cache `mcp-remote` : il est indexé par une empreinte de l'URL du serveur,
identique pour les deux sites. Une nouvelle autorisation écrase donc la précédente, et
l'autorisation en cache est rejouée en silence — l'écran de choix du site ne réapparaît qu'après
suppression de `~/.mcp-auth`.
