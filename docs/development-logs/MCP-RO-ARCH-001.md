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

- **Figma n'est toujours pas qualifié.** La suite reste hermétique pour ce fournisseur et les
  hash de schéma inscrits au registre restent à confirmer contre le serveur de production.
- **Classification trompeuse de deux erreurs de transport.** `httpx2.ConnectTimeout` n'hérite
  pas du `TimeoutError` natif, et un 401 fournisseur n'est pas distingué : les deux remontent en
  `MCP_TRANSPORT_FAILURE` (502) au lieu de `MCPCallTimeout` (504) et `MCPGrantUnavailable` (503).
  Le diagnostic oriente donc à tort vers un renouvellement de jeton. Non corrigé.
- **Budget de connexion de 3 s trop court** pour une sortie réelle depuis un poste de
  développement : des `ConnectTimeout` intermittents ont été observés sur des sondes isolées
  alors que le jeton et les liaisons étaient valides. Une sonde qui échoue seule pendant que les
  autres passent ne signale pas une expiration de jeton.
- **Le jeton de développement expire en une heure environ** et rien ne le rafraîchit : le
  courtier relit un fichier statique. Tout usage durable exige un compte de service et un vrai
  flux OAuth.
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

Corrigé au passage : `JIRA_SOURCE_ORIGIN` pointait vers
`https://andrianalyfanny-1786296714755.atlassian.net`, un hôte inexistant. Le site réel,
confirmé par `getAccessibleAtlassianResources`, est `https://andrianalyfanny.atlassian.net`
pour les deux produits. Toute citation Jira aurait été morte.

## Outillage

`scripts/mcp-smoke.sh` sonde les trois surfaces — identité seule, puis Jira et Confluence qui
exercent en plus l'injection du cloudId — et extrait `detail.code`, seul champ qui discrimine les
six causes regroupées sous 502.
