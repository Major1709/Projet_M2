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

## Figma : validation réelle et levée du quota — 2026-08-16

Le dernier critère d'acceptation encore ouvert de la tranche est levé. `extractFigmaProcess`
n'avait jamais vu une réponse de contenu réelle : il n'était éprouvé que contre des refus de
quota, c'est-à-dire contre des chemins d'erreur.

### Ce qui débloquait

Le plafond Figma suit **le fichier**, non le siège de l'appelant. Un fichier hébergé dans une
équipe au plan Starter est plafonné à environ six lectures de contenu par mois, quel que soit le
plan de qui le lit. La vérification Education obtenue le 2026-08-16 ne suffisait donc pas :
elle ouvre des droits sur une équipe, pas sur un fichier resté ailleurs.

La sortie n'a pas demandé de migration. Un fichier neuf créé dans l'équipe Education — une carte
FigJam `PROCESS`, clé `UVQmgXGaZC5vrtaQRU5nvo` — n'hérite d'aucun plafond Starter. Six appels
consécutifs sont passés là où l'ancien fichier refusait dès le premier, ce qui confirme par
l'expérience que la limite est portée par le fichier et non par le compte.

### Ce que la lecture réelle a prouvé

Les quatre outils répondent en 200 : `getFigmaFile` (1615 o), `getFigmaNode` (1327 o),
`renderFigmaNode` (URL d'image signée), `extractFigmaProcess`. Aucune ligne de code n'a été
modifiée pour y parvenir — le `fileKey` étant un argument d'appel depuis la refonte REST, un
fichier inconnu passe sans configuration. C'est la contrepartie recherchée de ce choix, et elle
est ici vérifiée plutôt que supposée.

L'extraction rend deux étapes et une transition :

```
START  ELLIPSE  kind=start   section=Section 1
LOGIN  SQUARE   kind=step    section=Section 1
1:3 → 1:13
```

L'invariant qui comptait est celui-là : `START` est classé point d'entrée **par connectivité** —
rien n'y arrive — et non parce qu'il porte ce nom. La règle était écrite depuis le début sans
avoir jamais été confrontée à un dessin réel. Elle tient.

Une réserve de conception subsiste, sans conséquence ici : `LOGIN` est classé `step` bien que
rien n'en sorte, la règle ne déclarant `end` que pour une forme arrondie. Un flux terminé par un
rectangle serait donc mal qualifié. À trancher quand une carte réelle présentera le cas.

### Correctifs d'accompagnement

`FIGMA_REFERENCE_FILE_KEY` pointe désormais vers la carte Education. Une référence documentaire
qui désigne un fichier devenu illisible ne documente rien.

Les deux README décrivaient encore Figma comme lu par son serveur MCP, et le `fileKey` comme une
constante non surchargeable — deux affirmations fausses depuis la bascule REST. L'écart était
plus grave qu'une simple péremption : il annonçait un contrôle qui n'existe pas. Les deux
fichiers énoncent maintenant la règle réelle, à savoir que la portée du jeton délégué est la
seule frontière de ce qui est lisible.

### Ce que cela laisse ouvert

La frontière étant à la maille du compte et non de l'équipe, restreindre le corpus suppose de
restreindre le compte porteur du jeton, pas la configuration. Par ailleurs les quatre outils
exigent tous une `fileKey` fournie : l'assistant ne sait pas énumérer ce qui existe. Un corpus
réduit à quelques fichiers de process s'en accommode ; un corpus défini comme « une équipe
entière » demandera un outil de découverte.

## Audit des appels au modèle — 2026-08-16

Livre la réserve H5 laissée ouverte par l'audit de sécurité : l'adaptateur ne devait pas être
câblé dans une boucle tant qu'un appel au modèle ne serait pas traçable. `generate` recevait un
`SecurityContext` sans jamais s'en servir.

### Un décorateur, pas du code dans l'adaptateur

`AuditedLLMProvider` enveloppe le port `LLMProvider` au lieu d'écrire la trace dans l'adaptateur
Groq. Un audit que chaque nouveau fournisseur doit penser à écrire est un audit qu'un nouveau
fournisseur finira par omettre ; envelopper le port le rend vrai pour toutes les implémentations,
y compris celles qui n'existent pas encore.

Le modèle demandé est lu sur le fournisseur — nouvelle propriété `model_name` — et non passé au
décorateur à la construction. Deux copies configurées du même fait divergent, et une trace
nommant un modèle que l'adaptateur n'a jamais demandé serait pire que pas de trace.

### Quatre événements, et l'ordre compte

`LLM_INVOCATION_AUTHORIZED` est écrit **avant** l'appel, comme `MCP_READ_AUTHORIZED` l'est avant
le transport. C'est ce qui rend un appel non enregistré impossible : un plantage entre les deux
laisse une invocation visiblement inachevée plutôt qu'aucune invocation. Si le puits d'audit
refuse cette écriture, le fournisseur n'est jamais atteint — échec en `LLM_AUDIT_UNAVAILABLE`.

Trois verdicts ensuite. `COMPLETED`. `REFUSED` quand le fournisseur écarte l'appel — identifiant
indisponible, DNS refusé, transport, quota, réponse invalide. `BOUNDED`, distinct, quand ce sont
**nos propres plafonds** qui ont arrêté l'appel : `LLM_REQUEST_TOO_LARGE`, `LLM_RESPONSE_TOO_LARGE`.
La distinction n'est pas cosmétique — un appel borné peut avoir produit une réponse partielle que
notre plafond a tronquée. C'est un fait sur le contenu, pas sur le fournisseur, et le confondre
avec un refus masquerait la troncature.

Une exception inattendue échappant à un adaptateur est un défaut, et le cas où la trace importe
le plus : elle est enregistrée sous `LLM_UNEXPECTED_FAILURE` avec le seul nom de son type, jamais
son message, qui peut transporter du texte fournisseur non borné.

### Ce qui n'entre pas dans la trace

Aucun texte de prompt ni de complétion. Les messages portent ce qui a été lu dans Jira,
Confluence ou Figma ; le recopier dans la table d'audit dupliquerait le corpus dans un support à
la rétention et au public différents. Sont enregistrés des comptes, les plafonds demandés, les
noms d'outils proposés avec leur `action_class`, et une empreinte `prompt_sha256` qui permet de
reconnaître deux prompts identiques sans en restituer le contenu. L'empreinte tolère une valeur
non sérialisable : échouer à empreindre ne doit jamais être la raison d'un refus d'appel.

### Corrélation de bout en bout

Le `correlation_id` de la requête est celui que portent les lectures MCP. Un test le vérifie sur
une trace complète : `LLM_INVOCATION_AUTHORIZED`, `LLM_INVOCATION_COMPLETED`, puis
`MCP_READ_AUTHORIZED` et `MCP_READ_COMPLETED`, tous sous le même identifiant. Une réponse de
l'assistant est donc reconstituable depuis la trace seule.

### Ce qui reste ouvert

Le décorateur n'est pas encore câblé dans `bootstrap.py`, faute de consommateur : le fournisseur
n'entre dans le conteneur qu'avec la boucle d'orchestration. Le câblage relève de cette tranche,
et c'est là que la réserve H5 se vérifiera en pratique. Un verdict `BOUNDED` pour un
`max_steps` épuisé n'existe pas non plus, la boucle qui pourrait l'atteindre n'existant pas.

## Boucle d'orchestration — 2026-08-16

Le chaînon manquant : l'adaptateur Groq et le pipeline MCP existaient des deux côtés sans rien
entre eux. `AgentReadWorkflow` enchaîne les tours — le modèle propose, le registre décide, le
résultat repart au modèle — jusqu'à réponse ou épuisement de `max_steps`.

### Ce que la boucle n'ajoute pas

Aucune autorité. La propriété à préserver est que **supprimer ce module n'élargirait rien** : le
catalogue montré au modèle est dérivé des schémas *publics* du registre, et chaque appel proposé
repasse par `MCPReadWorkflow`, qui le ré-autorise et injecte les liaisons côté serveur. Deux tests
le verrouillent — le catalogue est comparé champ à champ aux `public_input_schema`, et aucun
argument de liaison (`cloudId`, `siteUrl`, `accessToken`) ne doit y apparaître, faute de quoi le
modèle pourrait choisir un tenant, la seule chose qu'il ne doit jamais pouvoir faire.

Le prompt système énonce que le contenu lu est de la donnée, jamais des instructions. C'est une
atténuation, pas le contrôle : le contrôle est qu'un appel proposé ne peut être qu'une lecture
d'une source déjà couverte par le jeton délégué.

### Deux familles de refus

C'est la décision structurante. Un refus **récupérable** retourne au modèle sous forme
d'observation, et il se corrige : arguments hors schéma (`MCP_INPUT_REJECTED`), lecture refusée
par la source (`MCP_REMOTE_TOOL_FAILURE`), réponse trop grosse (`MCP_RESPONSE_TOO_LARGE`).

Tout le reste **arrête la boucle** : kill switch, outil non approuvé, grant absent, audit
indisponible, DNS, schéma, quota, transport. Réessayer contre une porte fermée brûle le budget de
jetons et masque le refus derrière une réponse vague.

Le défaut est l'arrêt, et c'est le point : une erreur ajoutée plus tard à la taxonomie est fatale
tant que personne n'a décidé du contraire, plutôt que confiée en silence à un modèle pour qu'il
la contourne. Seuls le code et le `safe_message` — tous deux les nôtres — entrent dans
l'observation, si bien qu'aucun texte fournisseur ne rejoint la transcription par un chemin
d'erreur.

### Un identifiant d'appel manquait

`ProposedToolCall` ne portait pas le `tool_call_id` du fournisseur, qu'un endpoint compatible
OpenAI exige sur chaque message de résultat. Ajouté et contraint aux ASCII imprimables plutôt que
seulement borné : la valeur est réémise telle quelle dans le corps de la requête suivante, donc un
retour à la ligne ou un caractère de contrôle y serait rejoué. Un appel sans identifiant est une
réponse malformée, pas quelque chose à rattraper par un identifiant fabriqué.

Le tour assistant réinjecté est **reconstruit** depuis les champs validés, non rejoué depuis le
message brut : la transcription ne contient alors que ce qui a passé les contrôles de
l'adaptateur, et rien que le fournisseur aurait envoyé sans qu'on le regarde.

### Le budget dicte la forme

Chaque tour renvoie la transcription entière, donc le coût croît avec le carré du nombre
d'étapes. `max_steps` vaut 4 par défaut et les observations sont tronquées à 6 000 caractères. La
troncature est **annoncée** dans l'observation : un modèle incapable de voir qu'il a reçu un
fragment répondra comme s'il avait tout reçu. Les octets d'image ne repartent jamais — seule une
référence, taille et empreinte.

### Ce qui reste pour la tranche B

Le câblage dans `bootstrap.py`, la route API et une sonde réelle. Rien de tout cela n'est encore
branché : la boucle est éprouvée contre un fournisseur simulé, sans réseau. C'est au câblage que
la réserve H5 se vérifiera en pratique, et que le plafond de jetons par minute se manifestera.

## Câblage et sonde réelle de l'agent — 2026-08-16

`bootstrap.py` construit l'agent, `POST /api/agent/questions` l'expose, et la chaîne complète a
répondu à une vraie question en lisant Jira.

### Le fournisseur nu n'entre pas dans le conteneur

`_build_agent` enveloppe systématiquement `GroqLLMProvider` dans `AuditedLLMProvider`. La
décoration est faite là plutôt que laissée à l'appelant : une invocation sans trace de son tenant
et de son utilisateur doit être **inatteignable par construction**, pas par le souvenir d'avoir
enveloppé au bon endroit. Un test lit la composition du conteneur pour le vérifier. C'est la
vérification pratique de la réserve H5, qui est donc levée.

L'agent vaut `None` quand aucun fournisseur n'est configuré, et les lectures MCP restent
disponibles : l'assistant est la couche optionnelle, pas les connecteurs en dessous. La route
répond alors `403 LLM_PROVIDER_DISABLED`, comme la couche MCP le fait pour un provider éteint.

### Une cause, un code

Les erreurs LLM ont leur table de traduction — 503 pour l'audit ou l'identifiant indisponible,
429 pour le quota, **413** pour une requête trop grosse puisque attendre n'y change rien, 504 pour
le délai, 502 pour le reste. Un refus de lecture jugé fatal par la boucle est traduit par la
table **de la couche MCP**, si bien qu'une même cause garde le même code qu'elle soit atteinte
directement ou à travers l'assistant.

### Ce que la sonde réelle a montré

```
Question : « Quels sont les projets Jira visibles ? Cite leur cle. »
Reponse  : « Il y a un projet Jira visible : KAN (Mon espace Kanban) »
Arret    : answered en 2 etapes, source getVisibleJiraProjects

LLM_INVOCATION_AUTHORIZED / COMPLETED
MCP_READ_AUTHORIZED / COMPLETED
LLM_INVOCATION_AUTHORIZED / COMPLETED     -- le tout sous un seul correlation_id
```

Le modèle a choisi l'outil, le registre l'a autorisé, la lecture a abouti contre le vrai serveur
Rovo, et la réponse cite un projet réel. La trace d'audit reconstitue l'enchaînement complet.

### Le plafond par minute est la contrainte dimensionnante

Au premier essai, deux questions enchaînées ont produit `LLM_RATE_LIMITED` sur le second appel de
la seconde question — après une lecture MCP réussie. Le catalogue pèse à lui seul ~1 800 jetons et
il est renvoyé à chaque tour ; avec le budget de complétion demandé compté qu'il soit consommé ou
non, deux tours à 1 200 jetons suffisent à approcher les 8 000 par minute du tier gratuit.

La sonde ne passe qu'en réduisant le budget à 700 jetons et en laissant la fenêtre se rouvrir.
C'est une limite de compte, pas de conception, mais elle borne en pratique l'agent à deux ou trois
étapes par question tant que le tier gratuit est utilisé.

### Constats annexes

Une invocation dont le budget de complétion est trop court échoue en `LLM_RESPONSE_TOO_LARGE`
avant d'avoir rien produit d'utile : le raisonnement consomme le budget avant que la réponse ne
commence. Observé à 400 jetons, résolu à 1 200. Le plancher utile est donc nettement plus haut que
le minimum accepté par le schéma.

`validate_runtime_adapters` exige le fichier de jeton **au niveau du provider** Atlassian, sans
tenir compte des surcharges par binding. Un déploiement qui ne renseignerait que
`PKA_MCP_ATLASSIAN_JIRA_BEARER_TOKEN_FILE` et son équivalent Confluence serait refusé alors que
l'amorçage fonctionnerait. Sans danger — le défaut va vers le refus — mais plus strict que
nécessaire. Non corrigé ici.

## Citations — 2026-08-16

`AgentAnswer` ne transporte plus la provenance brute mais une liste de sources dédupliquées.

### Un lien seulement quand il en existe un

Une source ne porte d'URL que si la lecture a produit un `resource_reference`. Celui-ci est
dérivé par le registre d'un **argument public obligatoire**, jamais relu depuis la réponse du
fournisseur : une citation ne peut donc pas être redirigée par un serveur compromis.

Un outil qui énumère au lieu de désigner — `getVisibleJiraProjects`, une recherche JQL — n'obtient
aucun lien. La source existe et nomme l'outil, mais son URL vaut `None`. Fabriquer un lien
plausible reviendrait à citer une page que personne n'a lue.

### Deux identités pour dédupliquer

Une ressource est identifiée par sa référence seule : le même ticket lu deux fois avec des champs
différents est **une** source, pas deux — ce n'est pas deux choses qu'un lecteur peut ouvrir. Une
collection, sans référence, est identifiée par la requête qui l'a produite : l'outil et l'empreinte
de ses arguments. Deux recherches différentes restent deux sources ; la répétition de la même se
replie.

L'ordre est celui de la première consultation, et une répétition ne peut qu'ajouter un drapeau,
jamais en retirer.

### Ce qui n'est pas exposé, et pourquoi

La provenance complète porte les empreintes de schéma et le `binding_fingerprint` : des faits sur
la manière dont la lecture a été faite et contre quel tenant. Ils appartiennent à la trace
d'audit, pas à une réponse remise à un appelant. Un test verrouille la liste exacte des champs
d'une source.

`source_complete` n'est **pas** remonté non plus, alors qu'il aurait été tentant de le faire. Le
workflow de lecture le laisse toujours à faux, faute de schéma de sortie authentifié attestant
qu'un corps est entier. Un champ constant ne porte aucune information mais se lit comme un signal,
et « toutes les sources sont incomplètes » est une affirmation pire que le silence. Il y reviendra
le jour où un fournisseur donnera de quoi le dériver.

En revanche `truncated` est exposé, et varie : il dit que **notre** plafond d'observation a coupé
le contenu avant que le modèle ne le voie. Distinct de `source_complete` — la lecture a réussi
entièrement, la perte est la nôtre, et c'est autre chose à dire à un lecteur.

### Sonde réelle

```
Question : « Que contient le ticket KAN-1 ? Resume-le en une phrase. »
Reponse  : « un bug de priorite moyenne intitule "test", statut "A faire", sans description »
Source   : getJiraIssue -> https://andrianalyfanny.atlassian.net/browse/KAN-1, tronquee=False
```

Une lecture indépendante de KAN-1 confirme `key: "KAN-1"` et `summary: "test"` : la citation
désigne bien la ressource que la réponse décrit.

## Découverte : ce que le modèle fait sans qu'on le lui dise — 2026-08-16

Le registre expose des points d'entrée sans argument obligatoire du côté Atlassian —
`getVisibleJiraProjects`, `getConfluenceSpaces`, `searchJiraIssuesUsingJql`,
`searchConfluenceUsingCql` — et aucun du côté Figma, où les quatre outils exigent un `fileKey`
fourni par l'appelant. La boucle n'avait jamais été éprouvée sur une question ne nommant aucune
ressource.

Une sonde l'a fait : « Sur quoi porte le travail suivi dans Jira en ce moment ? » Réponse correcte
en deux étapes, le modèle écrivant directement du JQL sans même énumérer les projets. **La
découverte Atlassian est donc acquise sans index et sans fournisseur d'embeddings.** Elle ne
manque que pour Figma.

Mais la sonde a révélé un défaut que le code seul ne montrait pas. La source était une recherche,
donc sans lien — conforme à la conception, une recherche ne désigne rien. Sauf que la réponse,
elle, **nommait KAN-1**. Le lecteur reçoit une affirmation sur une ressource identifiable en face
d'une source qu'il ne peut pas ouvrir.

Deux issues, et une seule est acceptable. Dériver les liens des résultats de recherche est facile
et casse l'invariant : la référence viendrait de la réponse du fournisseur au lieu d'un argument
public obligatoire, ce qui est précisément ce qui empêche aujourd'hui un serveur compromis de
rediriger une citation. Écartée. L'autre est d'amener le modèle à relire ce qu'il cite.

## Consigne de relecture : une mitigation, pas un contrôle — 2026-08-16

Le prompt système demande désormais explicitement de lire une ressource par son identifiant avant
d'affirmer quoi que ce soit à son sujet, et de ne pas relancer deux fois la même recherche.

**Elle a été mesurée insuffisante.** Sur la même question, quatre exécutions ont produit trois
entrées différentes : recherche puis lecture, recherche répétée à l'identique, énumération des
projets. Une exécution menée *après* l'ajout de la consigne a répété la recherche malgré elle, sur
un appel abouti — donc non imputable au quota.

La consigne est conservée, car elle oriente sans rien coûter, mais elle est doublée d'un garde-fou
déterministe. Ce qu'il faut retenir pour la suite : un prompt ne rend aucun comportement
impossible, et rien qui repose sur lui ne peut porter une garantie. La boucle reste sûre dans tous
les cas — ce qui varie est la citabilité d'une réponse, jamais ce qui peut être lu.

## Garde-fou contre la lecture répétée — 2026-08-16

Une lecture déjà effectuée avec exactement les mêmes arguments n'est plus rejouée. Le modèle
reçoit à la place une observation lui indiquant qu'il possède déjà ce résultat. La clé est
l'empreinte SHA-256 du nom d'outil et des arguments **triés** : un modèle qui réordonne les mêmes
clés ne passe pas à travers.

Trois décisions, et leurs raisons :

- **Le garde-fou n'ajoute aucune autorité.** Il ne sait que refuser un appel, jamais en élargir un.
  C'est ce qui permet de le placer dans la boucle d'orchestration plutôt que dans la couche MCP.
- **Seules les lectures réussies sont mémorisées.** Un échec n'a produit aucun résultat
  réutilisable, et son observation d'erreur invite justement à corriger les arguments : refuser la
  reprise piégerait un cas légitime. Un modèle qui échoue en boucle reste borné par la limite
  d'étapes.
- **La portée est la question, pas la session.** Une question ultérieure peut légitimement
  redemander la même chose, et mérite alors du contenu frais.

### Traçabilité d'un appel supprimé

Un pas qui ne produit aucune lecture serait autrement indiscernable d'un pas qui n'a jamais eu
lieu. `AGENT_TOOL_CALL_SKIPPED` enregistre donc `reason=duplicate`, le nom de l'outil,
l'empreinte des arguments et le `correlation_id`.

**Jamais les arguments eux-mêmes** : une clé de ticket ou une clause JQL peut nommer une personne
ou reformuler du contenu confidentiel, et la trace d'audit a une rétention et un public différents
de ceux du corpus qu'elle recopierait.

L'événement n'est précédé d'aucune autorisation, contrairement aux lectures : rien n'est sorti du
processus, et enregistrer un non-événement comme un appel autorisé corromprait le sens de la
trace. L'écriture reste néanmoins bloquante, comme toutes les autres — une trace fiable partout
sauf à un endroit est une trace sur laquelle personne ne peut raisonner, et à ce stade le puits a
déjà accepté plusieurs écritures dans la même requête.

### Ce que le garde-fou ne fait pas

Il supprime la répétition, pas la citation manquante. Le modèle peut toujours énumérer les projets
ou répondre à partir de la seule recherche, donc une réponse nommant un ticket sans lien cliquable
reste atteignable. L'interdire supposerait de refuser toute réponse finale tant qu'aucune ressource
n'a été lue, ce qui casserait les questions dont la réponse est légitimement une liste.

**Statut de vérification : garde-fou validé par tests unitaires uniquement.** Le parcours réel
`recherche → lecture → réponse citée` n'a jamais été observé en entier — seulement en deux morceaux,
sur des exécutions différentes. Le plafond de jetons par minute du palier gratuit a interrompu
chaque tentative de confirmation.

## Suites de la revue locale — 2026-08-16

### L'identité est vérifiée là où elle est utilisée

`get_development_security_context` lit `X-Tenant-ID` et `X-User-ID` sans les vérifier, et c'est la
dépendance de toutes les routes. La protection existait, mais loin du risque : `auth_mode` n'admet
qu'une seule valeur et la configuration refuse `production` tant que cette valeur est
`dev_headers`, ce qui rend aujourd'hui la production littéralement inconstructible.

**La sûreté reposait donc sur une annotation de type à un seul membre, pas sur le code de la
requête.** Ajouter `"oidc"` à ce `Literal` — geste attendu au moment d'implémenter l'IAM — aurait
rendu la production constructible pendant que chaque route continuait de croire les en-têtes. La
trace d'audit aurait alors enregistré un locataire choisi par l'appelant : pire qu'une trace
absente, puisque les valeurs paraissent plausibles.

La dépendance consulte désormais `auth_mode` elle-même et refuse la requête pour tout mode qu'elle
n'implémente pas. Le point d'application est revenu là où est le risque, et l'ajout d'un mode ne
peut plus élargir l'accès par inadvertance.

### Le nombre de lectures d'une question est borné

`max_steps` ne bornait que les étapes. Un tour peut porter plusieurs appels — l'adaptateur en
accepte huit — donc huit étapes de huit appels faisaient **soixante-quatre lectures**, chacune avec
son propre budget de transport. Une question pouvait occuper le processus plusieurs minutes et
consommer le quota d'une source bien au-delà de ce que `max_steps` laissait croire à qui l'avait
réglé.

Un plafond de **quatre** lectures par question s'applique désormais à toutes les étapes confondues.
Quatre est ce que coûte une vraie question — chercher puis lire, sur chacune de deux sources. Les
valeurs plus généreuses ne sont pas seulement larges, elles sont impayables : douze lectures au
budget de transport de trente secondes font six minutes sur une seule question, et suffisent à
dépasser l'allocation de dix par minute de certains points d'accès Figma.

Un déploiement peut relever ce chiffre, jamais au-delà d'un plafond absolu de douze — une limite
qu'on peut porter à n'importe quelle valeur n'est pas une limite. Le réglage appartient au
déploiement et **jamais à la requête** : un plafond choisi par l'appelant est un plafond que
l'appelant relève.

Le compteur suit les tentatives et non les succès, car une lecture qui échoue a tout de même
atteint la source. Certaines erreurs sont refusées avant de l'atteindre réellement, ce qui rend le
bornage un peu plus strict qu'exact — dans le bon sens.

Un appel écarté avant le transport — doublon, ou plafond atteint — ne consomme rien : le garde-fou
protège le budget, il ne le dépense pas.

### Une réponse interrompue le dit

La boucle renvoyait le texte du dernier tour. Or un tour qui propose des outils n'en porte
généralement aucun : une question arrêtée par la limite d'étapes produisait donc un **200 au corps
vide**. Le client affichait une réponse blanche et le lecteur n'apprenait jamais que l'assistant
avait été interrompu plutôt que silencieux.

Seul un tour non vide est désormais retenu, de sorte qu'un tour d'outils n'efface plus la dernière
phrase réelle du modèle ; et à défaut de toute phrase, un message serveur explicite est substitué.

### Permissions d'un document de credentials réimporté

`os.open(..., 0o600)` n'honore le mode qu'à la **création**. Réimporter par-dessus un fichier
existant conservait ses droits d'origine, alors que le document porte `access_token`,
`refresh_token` et, pour Figma, `client_secret`. Un `chmod` explicite suit désormais l'écriture.

Le modèle est **prévenu** plutôt que coupé : il reçoit une observation lui demandant de répondre
avec ce qu'il a et de dire ce qui lui manque. `AGENT_TOOL_CALL_SKIPPED` porte maintenant
`reason=read_limit` à côté de `reason=duplicate`.

### Un nom d'outil inventé ne tue plus la question

L'adaptateur levait `LLMInvalidResponse` dès qu'un nom proposé ne figurait pas dans le catalogue,
ce qui remontait en **502** et perdait toute la question. Or inventer un nom d'outil est la faute
la plus banale d'un modèle, et c'est exactement la classe d'erreur que cette boucle existe pour
absorber. Le chemin de repli était d'ailleurs déjà écrit dans `_observe`, mais inatteignable.

L'autorité est désormais unique : **le registre**. L'appel traverse l'adaptateur — borné et
restreint aux caractères imprimables comme n'importe quel nom — puis la boucle le refuse contre le
registre, l'inscrit à l'audit sous `reason=unknown_tool` et rend une observation au modèle.

Rien n'est élargi : un nom non autorisé n'atteint aucun transport, il obtient seulement une phrase
lui demandant de choisir un outil réel. Cette phrase **ne répète pas le nom** : il vient du
fournisseur, et le recopier dans la transcription laisserait un fournisseur compromis placer le
texte de son choix dans nos propres mots. La trace d'audit, elle, le conserve — c'est là qu'un
appel rejeté doit vivre.

### Le plancher de `max_completion_tokens` est celui qu'on a mesuré

Le minimum du schéma passe de 64 à 768. Sur un modèle à raisonnement, un plafond bas ne produit pas
une réponse courte : il n'en produit **aucune**, avec `finish_reason == "length"`, pour le même
budget consommé. Échec observé à 64 et à 450, succès à 700. Accepter 64 revenait à promettre par
contrat un appel qui ne peut pas fonctionner.

### Un puits d'audit en panne n'efface plus la cause

Sur les deux chemins de refus, l'écriture d'audit précédait la journalisation. Si le puits tombait,
`MCPAuditUnavailable` remplaçait l'erreur d'origine **avant** qu'elle soit journalisée : un
`MCPToolDenied` devenait un 503 générique et disparaissait aussi des journaux.

La journalisation vient désormais en premier. L'échec du puits lui-même est journalisé à son tour,
avec le **type** de l'exception seulement — un message de puits peut porter une chaîne de connexion
ou un fragment de la ligne qu'il écrivait. Le comportement fail-closed est inchangé ; seule la
perte de diagnostic est corrigée.

### La connexion va à l'adresse qui a été approuvée

Les trois adaptateurs résolvaient le nom d'hôte, validaient chaque adresse, puis construisaient
leur client **sur le nom d'hôte** — que httpx résolvait une seconde fois. C'est cette seconde
réponse qui était contactée. Un résolveur compromis pouvait donc répondre publiquement à la
vérification et en interne à la connexion, ce qui vidait le contrôle de sa substance.

Un transport partagé, `PinnedAddressTransport`, réécrit désormais la requête vers l'adresse
approuvée. **Seul l'hôte change** : schéma, port, chemin et requête restent tels que l'appelant les
a construits, faute de quoi un garde-fou censé fixer la destination pourrait déplacer la requête
vers une autre ressource.

L'identité de la destination est préservée — `Host` pour le routage côté serveur, et le nom SNI
pour la poignée de main. La vérification du certificat continue donc de se faire contre le nom
d'hôte : **épingler l'adresse ne doit pas devenir un moyen d'accepter un certificat qui n'a jamais
été valide pour elle.** C'est le point qui aurait pu transformer un correctif anti-SSRF en faille
TLS.

Un seul exemplaire pour les trois adaptateurs, pour la raison déjà écrite en tête de `http_guard` :
deux copies d'un contrôle d'adresse font deux endroits à affaiblir, et le second est celui que
personne ne relit.

## La passerelle branchée sur le backend — 2026-08-17

Le frontend parlait jusqu'ici à `demoAssistantGateway`, un adaptateur qui attend 550 ms et renvoie
un texte fixe. La passerelle elle-même — `ProjectAssistantGateway` — est un port de trois méthodes :
`sendMessage`, `indexRequests`, `decideAction`. **Une seule des trois a une contrepartie serveur**,
et c'est le fait structurant de cette tranche.

`createHttpAssistantGateway` appelle `POST /api/agent/questions` avec `X-Tenant-ID` et `X-User-ID`,
et projette `AgentAnswer` en `ChatMessage`. Trois décisions valent d'être écrites :

- **Le `correlation_id` devient l'identifiant du message.** Il est généré côté navigateur, envoyé
  dans le corps, et conservé comme `id`. C'est lui qui relie une réponse affichée à ses lectures
  dans la trace d'audit : un `Date.now()` aurait été unique sans être retrouvable.
- **`confidence` et `inferred` restent vides.** Le modèle `SourceReference` les déclare, la maquette
  les affiche sous la forme « IA · 87 % », et le backend ne produit ni l'un ni l'autre — ses
  citations viennent de la provenance des lectures réellement effectuées. Les remplir d'une valeur
  plausible aurait affiché une mesure que rien ne mesure. Même raisonnement que pour
  `source_complete`, écarté d'`AgentSource` pour la même raison.
- **`truncated` est affiché**, dans `location`, parce que c'est la seule information qu'un lecteur ne
  peut pas déduire du lien : la réponse a été formée sur un fragment.

`SourceSystem` gagne `"atlassian"`. Le backend l'émet lorsqu'une lecture est passée par le serveur
MCP Atlassian sans que l'outil désigne Jira ou Confluence ; le rabattre sur l'un des deux aurait
nommé un produit que personne n'a vérifié.

**Les deux autres méthodes refusent au lieu de simuler.** `indexRequests` n'a aucune contrepartie —
il n'existe pas d'index, les lectures sont pilotées par les recherches du modèle — et un succès
fabriqué aurait marqué les demandes `INDEXED` dans le navigateur. `decideAction` a bien une API
d'approbations, mais elle décide sur des propositions créées par le serveur, et ce build n'en
produit aucune : les mutations sont désactivées. Un `APPROVED` affiché aurait montré une décision
enregistrée nulle part.

Le hook distingue désormais un `AssistantGatewayError` — un refus déjà rédigé pour le lecteur, qui
dit quoi faire — d'une exception quelconque, dont le message est écrit pour un développeur et ne
doit pas entrer dans la conversation. Les statuts sont traduits un par un : 429 « réessayez dans une
minute », 413 « reformulez plus court, attendre ne changera rien », 503 « l'assistant refuse de lire
sans pouvoir consigner ». Le `detail.message` du backend n'est jamais affiché : il est écrit pour un
opérateur et peut citer le fournisseur.

### CORS, ajouté parce que sans lui rien ne part

Le navigateur refusait la requête avant de l'émettre : en-têtes personnalisés, donc préflight, donc
CORS obligatoire. `PKA_FRONTEND_ORIGINS` est **vide par défaut**, et le middleware n'est alors pas
installé du tout. Origines exactes uniquement, ni joker ni expression régulière — les en-têtes
d'identité sont le locataire, donc une origine autorisée à les envoyer est une origine autorisée à
choisir un tenant. `allow_credentials` reste faux, HTTP simple n'est toléré que sur `localhost`, et
une valeur non conforme est refusée à la construction : un joker accepté ici ne se découvrirait
qu'en constatant qu'une page que personne n'a déployée appelle l'API avec son propre tenant.

Le point de composition est unique : `ProjectAssistantScreen` choisit l'adaptateur selon
`NEXT_PUBLIC_ASSISTANT_API_URL`, et retombe sur la démonstration si les trois variables ne sont pas
toutes présentes — un build sans backend ne doit pas proposer un assistant qui échoue à chaque
message. Le tenant et l'utilisateur viennent de l'environnement parce que ce build n'authentifie
personne : c'est le mode `dev_headers`, que les settings du backend interdisent en production. Cette
configuration ne peut donc pas être déployée telle quelle, et la couture à remplacer est là.

**Non vérifié en réel :** aucun aller-retour navigateur → backend → Groq n'a été joué. Ce qui est
prouvé l'est par tests — 21 côté frontend, dont la forme exacte de la requête, la traduction des six
statuts et les deux refus ; 12 côté backend pour CORS. Le parcours `recherche → lecture → réponse
citée` reste par ailleurs bloqué par le quota du palier gratuit, comme consigné plus haut.

## Phase 0 : la chaîne prouvée jusqu'à l'avant-dernier appel — 2026-08-17

Première exécution réelle de bout en bout, `correlation_id` `phase0-20260817T192007Z`. Six
événements d'audit, tous sous le même identifiant :

| # | Événement | Durée | Contenu |
|---|---|---|---|
| 1 | `LLM_INVOCATION_AUTHORIZED` | — | 15 outils exposés, empreinte du prompt |
| 2 | `LLM_INVOCATION_COMPLETED` | 6 046 ms | Choisit `getJiraIssue`, `text_characters: 0` |
| 3 | `MCP_READ_AUTHORIZED` | — | jira / `getJiraIssue`, `SPEC-MCP-RO-001-r2` |
| 4 | `MCP_READ_COMPLETED` | 9 448 ms | Lecture Jira réelle, protocole `2025-11-25` |
| 5 | `LLM_INVOCATION_AUTHORIZED` | — | Second appel, transcript à 4 messages |
| 6 | `LLM_INVOCATION_REFUSED` | 607 ms | `LLM_RATE_LIMITED` |

**Ce qui est désormais prouvé :** question → sélection d'outil → lecture Jira réelle. Le modèle est
allé directement à `getJiraIssue` sans énumérer les projets, ce qui confirme que nommer le projet
dans la question évite l'étape d'énumération et raccourcit la chaîne d'un appel.

**Ce qui ne l'est pas :** la synthèse finale citée, refusée pour épuisement de quota au dernier
appel — un budget, pas un défaut. Et l'aller-retour depuis un vrai navigateur : la requête a été
émise par `curl` avec l'en-tête `Origin`, ce qui exerce la politique CORS mais pas le client.

**CORS vérifié dans les deux sens.** Origine déclarée : `200` avec
`access-control-allow-origin` et les deux en-têtes d'identité admis. Origine inconnue : `400`
**sans** l'en-tête d'autorisation, donc bloquée par le navigateur. `allow_credentials` reste absent.

### Trois variables de configuration ne servaient à rien

Les settings utilisent `env_prefix="PKA_"` avec `extra="ignore"` : toute variable sans ce préfixe
est ignorée en silence.

- `BACKEND_CORS_ORIGINS` n'a jamais été lue. Le seul levier réel, `PKA_FRONTEND_ORIGINS`, était
  **absent** du `compose` et du `.env` — donc aucun middleware CORS n'était installé.
- `MAX_AGENT_STEPS=12` laissait croire à un plafond de douze étapes. Le vrai est
  `DEFAULT_MAX_STEPS = 4`, en dur. Supprimée.
- `EMBEDDING_MODEL=BAAI/bge-m3` contredisait la décision prise le même jour. Alignée sur
  `intfloat/multilingual-e5-base`, avec la mention explicite qu'aucun code ne la lit encore.

### L'image déployée avait plusieurs tranches de retard

Le conteneur `api` qui tournait n'exposait ni `/api/agent/questions` ni la politique CORS : son
image précédait toute la tranche d'orchestration. « La pile tourne » ne disait donc rien de ce
qu'elle servait. Reconstruite avant la sonde.

### Le corpus Jira est vide

`getVisibleJiraProjects` retourne un seul projet, `KAN`, contenant un seul ticket, `KAN-1`, un bug
intitulé « test ». Suffisant pour prouver une lecture et une citation ; **insuffisant pour
démontrer un rapprochement sémantique**, qui exige des tickets décrivant des sujets voisins avec
des formulations différentes. C'est un prérequis de la phase 3, à traiter avant elle et non pendant.

## Phase 0 close : le parcours complet depuis le navigateur — 2026-08-18

Rejeu depuis un vrai navigateur, une seule tentative, sans appel Groq preparatoire.
`correlation_id` `327bda05-88de-49db-b2f6-5d7edf87bd73`, genere cote navigateur et repris tel quel
comme identifiant du message.

Question posee dans l'interface : « Dans le projet Jira KAN, quel est le resume et le statut du
ticket KAN-1 ? »

| # | Evenement | Duree | Contenu |
|---|---|---|---|
| 1 | `LLM_INVOCATION_AUTHORIZED` | — | 15 outils exposes |
| 2 | `LLM_INVOCATION_COMPLETED` | 2 266 ms | 0 caractere, choisit `getJiraIssue` |
| 3 | `MCP_READ_AUTHORIZED` | — | jira / `getJiraIssue` |
| 4 | `MCP_READ_COMPLETED` | 15 159 ms | Lecture Jira reelle |
| 5 | `LLM_INVOCATION_AUTHORIZED` | — | Second appel |
| 6 | `LLM_INVOCATION_COMPLETED` | 1 468 ms | 84 caracteres, aucun outil : la synthese |

Reponse rendue : « Pour le ticket **KAN-1** : **Resume (Summary)** : test — **Statut** : A faire ».
Elle correspond exactement a ce que `getVisibleJiraProjects` et `searchJiraIssuesUsingJql` avaient
montre en lecture directe. **Aucun `LLM_INVOCATION_BOUNDED`** : la reponse n'est pas tronquee.

La citation affichee pointe vers `https://andrianalyfanny.atlassian.net/browse/KAN-1`, verifie dans
le DOM. C'est le seul lien Jira de la page hors fixtures.

**Le parcours navigateur -> frontend -> backend -> Groq -> MCP Jira -> synthese -> citation est
donc prouve de bout en bout.** Le dernier ecart de la tranche est leve.

Deux observations que seule l'execution reelle pouvait donner :

- **La source reelle ne porte aucun pourcentage**, la fixture de demonstration juste au-dessus
  affiche « IA · 86 % ». C'est le champ `confidence` laisse vide faute de contrepartie backend, et
  le contraste est visible a l'ecran.
- **La lecture MCP domine le temps de reponse** : 15,2 s sur 19,0 s au total, contre 3,7 s cumules
  pour les deux appels au modele. L'optimisation eventuelle est du cote de la source, pas du LLM.

### Deux libelles de l'interface mentent desormais

Herites de l'ere demonstration, ils etaient exacts tant que la passerelle etait factice :

- `message-composer.tsx` affiche « Reponse simulee · aucune connexion MCP » sous la zone de saisie.
- `assistant-workspace.tsx` affiche « Aucune donnee n'est envoyee a une source externe. »

Les deux sont faux des lors que l'adaptateur HTTP est actif : la reponse est reelle, une lecture MCP
a eu lieu, et la question part vers Groq. A conditionner sur l'adaptateur reellement utilise, ou a
retirer. Consigne en dette, non corrige dans cette tranche pour ne pas melanger la preuve et un
changement d'interface.

## Phase 1 : la conversation survit au rechargement — 2026-08-18

Deux tables, `conversation_messages` et `message_sources`. La table `conversations` ne portait
que le fil ; une page rechargée revenait vide.

### Ce qui a été décidé, et pourquoi

**`conversation_id` est optionnel sur `AgentQuestion`.** Absent, le comportement est celui
d'avant ; présent, les deux tours sont enregistrés. Le rendre obligatoire aurait cassé le
frontend le jour même, alors que le chantier de rhabillage démarre en parallèle et qu'il ne
demandait pas encore cette fonctionnalité.

**Le tour utilisateur s'écrit avant l'appel, la réponse après.** Un `429` laisse donc une
question sans réponse à côté, ce qui est la description exacte de ce qui s'est produit. En
revanche une conversation inconnue, ou appartenant à quelqu'un d'autre, est refusée **avant**
l'appel : le découvrir ensuite aurait gaspillé un budget réel pour une réponse que personne ne
peut recevoir.

**Un échec d'écriture ne fait pas échouer la réponse.** Écart assumé avec l'audit, qui reste
fail-closed. Les deux ne protègent pas la même chose : une lecture non consignée est un trou de
gouvernance, une ligne de conversation perdue est une gêne. Refuser une réponse déjà payée en
appel au modèle et en lecture Jira détruirait plus que le défaut évité — et l'audit garde le
récit complet.

**Deux invariants sont dans le schéma, pas dans le code.** La clé étrangère embarque la colonne
propriétaire, sur le modèle de `action_proposals` : écrire dans le fil d'autrui est rejeté par
PostgreSQL. Et `message_sources` n'a de colonne ni pour un score de confiance ni pour un
drapeau d'inférence — la décision prise au niveau de l'API devient impossible à contourner par
le stockage.

Vérifié contre le PostgreSQL du `compose` : rattacher un tour à la conversation d'un autre
échoue sur `fk_conversation_messages_tenant_conversation_owner`, deux tours au même rang sur
`uq_conversation_messages_tenant_id_conversation_id_sequence`.

### Un défaut trouvé par les tests, pas par la relecture

L'ordre des tours était **aléatoire**. L'horloge Windows a une résolution d'environ 15 ms : les
deux tours d'un même échange tombent dans le même tic, `created_at` est identique, et le
départage tombait sur un UUID aléatoire. La conversation s'affichait à l'envers environ une fois
sur deux.

Ce défaut ne se serait pas vu en relecture, et se serait manifesté en production comme « les
messages sont parfois dans le désordre » — irreproductible à la demande. Corrigé par une colonne
`sequence` explicite, unique par fil, attribuée dans la même transaction que l'insertion : deux
tours concurrents se heurtent alors à la contrainte plutôt que de prendre silencieusement le
même rang. Un test de régression joue deux échanges consécutifs et vérifie les quatre rangs.

### Périmètre

Le plafond de lecture est serveur, à 200 tours, et une demande supérieure est **refusée** plutôt
que réduite en silence. Reste à faire : le branchement dans l'interface, qui appartient au
chantier de rhabillage, et le sort d'`indexRequests` dans le port — repoussé pour ne pas déplacer
le sol sous ce chantier.

## Phase 2, premiere tranche : la session cote serveur — 2026-08-18

Le defaut le plus grave du systeme est traite : l'appelant ne choisit plus son locataire.

### Additif, et c'est le point

`auth_mode` accepte desormais `session` en plus de `dev_headers`, et **garde `dev_headers` par
defaut**. Le chantier de rhabillage tourne en parallele et envoie encore les en-tetes d'identite ;
basculer le mode maintenant l'aurait casse pour une fonctionnalite qu'il n'a pas demandee.

C'est exactement l'extension que le controle de mode sur le chemin de requete avait prevue :
ajouter un mode n'accorde pas silencieusement un chemin qui continue de faire confiance a ce
qu'il faisait confiance avant.

### Les cinq proprietes qui comptent

**Les en-tetes deviennent inertes en mode session** — pas meme un repli en dernier recours. Un
repli rendrait a l'appelant precisement ce qu'on vient de lui retirer. Un test le prouve par ce
qu'un appelant peut lire, pas en inspectant le contexte : une session valide plus des en-tetes
usurpes donne l'identite de la session, et l'identite usurpee ne peut pas atteindre la
conversation creee.

**Un magasin injoignable repond 503.** Fail-closed : une identite qu'on ne peut pas verifier ne
doit pas etre affirmee, et les en-tetes attendent juste a cote comme solution de facilite.

**Le jeton n'est jamais stocke.** 256 bits d'urandom remis une fois au navigateur, seule
l'empreinte SHA-256 vit en base. Un vidage de base ne rend aucune session utilisable. SHA-256 nu
plutot qu'un hachage de mot de passe, faute d'entree devinable a ralentir et parce que le cout se
paierait sur chaque requete authentifiee.

**L'expiration est absolue, pas glissante.** Une session qui se renouvelle a chaque requete ne se
termine jamais pour qui detient le jeton — le cas meme contre lequel l'expiration existe. Une
session expiree repond comme une session absente, pour ne rien dire d'un jeton dont l'appelant
n'est peut-etre pas proprietaire.

**La table `sessions` n'est pas clef-par-locataire**, contrairement a toutes les autres. C'est
elle qui etablit le locataire : elle ne peut pas en dependre.

### Un choix qui contredit la feuille de route

Elle annoncait Redis, deja lance dans le `compose` sans consommateur. C'est PostgreSQL qui a ete
retenu : la consultation de session est sur le chemin de **chaque requete authentifiee**, et y
placer un second magasin ajouterait une bibliotheque cliente, un identifiant et un mode de panne a
un code dont toute la discipline est une surface sortante etroite. Les sessions sont peu
nombreuses, courtes, et balayees par l'expiration.

Redis reste donc sans consommateur. C'est un point de menage du `compose`, pas une raison
d'ecrire du code.

### Ce qui manque encore

Il n'existe **aucun moyen d'ouvrir une session** : ni page de connexion, ni flux OAuth. Le mode
est donc utilisable en test mais inutile en deploiement — personne ne peut entrer, ce qui est
fail-closed mais sterile. La suite de la phase 2 est le flux Atlassian 3LO, la table des
habilitations deleguees et le verrou partage du renouvellement.

## Phase 2.3 : le flux Atlassian, du consentement a la session — 2026-08-18

Le mode session existait sans moyen d'ouvrir une session. Trois routes le remplissent :
`/api/auth/atlassian/start`, `/callback` et `/signout`.

### Le tenant est derive, jamais declare

C'est le seul point qui compte vraiment. Un jeton delegue Atlassian couvre **exactement le site
choisi sur l'ecran de consentement**, et rien dans le jeton ne dit lequel : `accessible-resources`
est le seul moyen de l'apprendre. Ce projet l'avait deja appris a ses depens, c'est la raison
d'etre de l'option `--attendu` du script d'import.

Le `cloudId` devient donc le tenant et l'`account_id` devient l'utilisateur, tous deux relus chez
le fournisseur. C'est toute la difference avec le mode en-tetes qu'il remplace, ou l'appelant
choisissait les deux.

### Ce qui n'est pas negociable dans ce flux

**PKCE en S256 seulement.** Le verifieur n'apparait jamais dans l'URL d'autorisation : l'y mettre
defait la seule chose que PKCE apporte. Un test verifie que le defi publie a la premiere etape est
bien l'empreinte du verifieur envoye a la seconde — sans quoi l'appariement ne prouve rien.

**`prompt=consent` est explicite.** Sans lui Atlassian peut reutiliser un octroi anterieur en
silence, et l'utilisateur ne voit jamais le selecteur de site — l'ecran qui decide quel site le
jeton couvrira. **`offline_access` de meme** : sans refresh token, retour au consentement dans
l'heure.

**L'etat est a usage unique par construction.** Il est *retire* du magasin, pas lu. Un callback
rejoue frapperait sinon une seconde session dans un seul consentement.

**Les trois appels sortants suivent la discipline du projet** : HTTPS valide a l'import, port fixe,
redirections refusees, `trust_env` ignore, adresse resolue puis epinglee avec le nom conserve pour
SNI, reponse bornee a 256 Ko. Un code d'autorisation et un refresh token le meritent au moins
autant qu'une lecture MCP.

**Le corps du fournisseur n'est jamais reexpedie.** Il peut renvoyer le code en echo, nommer le
client, ou decrire l'echec dans des termes ecrits pour un operateur.

**`DelegatedCredentials` ne se represente pas.** Son `repr` ne montre que le tenant et
l'utilisateur : un refresh token dans un `repr` finit dans la premiere trace d'appel qui le touche,
puis dans un journal, puis dans une sauvegarde.

**Le cookie** porte `httponly`, `secure` partout sauf sur localhost en clair, `samesite=lax` et le
chemin racine. La deconnexion **revoque cote serveur avant** de vider le cookie : vider seulement
le cookie laisserait une session vivante pour quiconque a deja copie le jeton, ce qui est
precisement le cas auquel une deconnexion doit repondre.

### Trois refus a la construction

Un sign-in active sans son enregistrement, une cible de redirection en HTTP clair hors localhost,
ou une cible post-connexion qui est une URL complete plutot qu'un chemin — cette derniere etant la
definition d'une redirection ouverte. Echouer au demarrage vaut mieux qu'echouer au callback, ou
l'utilisateur est deja a mi-chemin d'un ecran de consentement.

### Ce qui reste

Les identifiants delegues vont dans un **port**, pas dans une table. L'implementation persistante et
chiffree est la tranche 2.4 ; en attendant ils vivent en memoire de processus et **jamais sur
disque**, ce qui force un nouveau consentement au redemarrage plutot que de laisser un refresh token
dans un fichier que personne ne fait tourner.

Consequence a ne pas oublier : le courtier d'habilitations que les lectures MCP utilisent lit
encore des fichiers designes par la configuration. Tant que 2.4 n'est pas livree, se connecter
donne une session mais pas une habilitation par utilisateur.

Rien de ce flux n'a ete joue contre le vrai Atlassian : il n'y a pas d'application OAuth
enregistree. Les 17 tests passent par un transport injecte.

## Dette technique

- **Deux fichiers de secrets sont en réalité des répertoires.** `infra/secrets/dev/`
  contient `atlassian_jira_bearer_token` et `atlassian_confluence_bearer_token` sous forme de
  dossiers, créés comme points de montage par Docker. Sans conséquence — le déploiement passe par
  le document OAuth renouvelable — mais un `MCP_GRANT_UNAVAILABLE` trompeur attend quiconque
  pointera une configuration vers ces chemins.
- **`validate_runtime_adapters` est plus strict que nécessaire sur Atlassian.** Elle exige le
  fichier de jeton au niveau du provider sans tenir compte des surcharges par binding, donc un
  déploiement ne renseignant que les fichiers Jira et Confluence serait refusé alors que
  l'amorçage fonctionnerait. Le défaut va vers le refus, donc sans danger.
- **Une réponse à `max_completion_tokens` trop bas échoue sans rien produire.** Le raisonnement
  consomme le budget avant que la réponse ne commence ; observé à 400 jetons, résolu à 1 200. Le
  plancher utile est très au-dessus du minimum accepté par le schéma, qui ne le reflète pas.

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
