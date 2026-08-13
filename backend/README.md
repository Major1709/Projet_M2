# Backend du Project Knowledge Assistant

Backend FastAPI du monolithe modulaire. Il persiste les conversations, les
propositions d'action et leur audit dans PostgreSQL, tout en conservant un mode
mémoire réservé au développement et aux tests unitaires.

## Installation et tests unitaires

Depuis `backend/` :

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest -m "not integration"
.venv\Scripts\ruff check app tests
```

Les tests unitaires utilisent `PKA_REPOSITORY_BACKEND=memory`, valeur par défaut.
Les données sont alors locales au processus et disparaissent au redémarrage.

Pour lancer l'API dans ce mode :

```powershell
$env:PKA_ENVIRONMENT = "development"
$env:PKA_REPOSITORY_BACKEND = "memory"
.venv\Scripts\python -m uvicorn app.main:app --reload
```

## Configuration PostgreSQL

Le backend n'accepte aucun DSN ni URL de base de données en variable
d'environnement. PostgreSQL exige toujours les paramètres séparés suivants :

- `PKA_REPOSITORY_BACKEND=postgres` ;
- `PKA_DATABASE_HOST` ;
- `PKA_DATABASE_PORT` ;
- `PKA_DATABASE_NAME` ;
- `PKA_DATABASE_USER` ;
- `PKA_DATABASE_PASSWORD_FILE` ;
- `PKA_DATABASE_POOL_SIZE`, valeur par défaut `5` ;
- `PKA_DATABASE_MAX_OVERFLOW`, valeur par défaut `10` ;
- `PKA_DATABASE_CONNECT_TIMEOUT_SECONDS`, valeur par défaut `2` ;
- `PKA_DATABASE_POOL_TIMEOUT_SECONDS`, valeur par défaut `2` ;
- `PKA_DATABASE_STATEMENT_TIMEOUT_MS`, valeur par défaut `2000`.

`PKA_DATABASE_PASSWORD_FILE` désigne un fichier monté à l'exécution. Le mot de
passe ne doit jamais être placé dans une variable, une commande, un fichier
versionné, un log ou un prompt. L'URL SQLAlchemy est construite en mémoire avec
`URL.create`; les paramètres SQL et identifiants de connexion sont masqués par le
moteur.

## Démarrage Docker : PostgreSQL, migration, API

Préparer `infra/.env` et les fichiers sous `infra/secrets/dev/` selon
`infra/README.md`, puis exécuter dans cet ordre depuis la racine du dépôt :

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml config --quiet
docker compose --env-file infra/.env -f infra/compose.yaml build api migrate
docker compose --env-file infra/.env -f infra/compose.yaml up -d --wait postgres
docker compose --env-file infra/.env -f infra/compose.yaml --profile ops run --rm migrate
docker compose --env-file infra/.env -f infra/compose.yaml up -d --wait api
Invoke-RestMethod http://localhost:8000/health/ready
```

Les migrations sont explicites : l'API ne crée et ne modifie jamais le schéma au
démarrage. Alembic doit atteindre `head` avant le lancement de la nouvelle version.
Ne pas utiliser de migration descendante ou supprimer un volume pour corriger un
échec. Une opération destructive exige une décision, une sauvegarde vérifiée et un
plan de restauration.

## Santé et cycle de vie

- `GET /health/live` confirme uniquement que le processus répond et reste à `200`
  même si PostgreSQL est indisponible.
- `GET /health` et `GET /health/ready` exécutent `SELECT 1`. Une base indisponible
  produit un `503` générique sans exposer la connexion ni les paramètres SQL.
- Le pool utilise `pool_pre_ping`; le lifespan FastAPI libère le moteur à l'arrêt.

Le budget client de readiness est de trois secondes et le healthcheck Compose
expire après cinq secondes. Le délai de connexion psycopg et l'attente maximale du
pool sont donc bornés par défaut à deux secondes. PostgreSQL reçoit aussi un
`statement_timeout` de deux secondes pour éviter qu'une sonde connectée reste
bloquée sur une requête. Les trois délais sont configurables dans les bornes
validées ci-dessus ; les augmenter exige d'aligner explicitement les budgets des
clients et healthchecks.

## Approbations et sécurité

`POST /api/actions` produit un jeton de décision aléatoire de 256 bits. Le jeton
brut est retourné une seule fois dans la réponse de création. Une révision retourne
de la même manière un nouveau jeton pour le snapshot de remplacement. `GET` ne
retourne jamais de jeton ni d'empreinte.

Seul le SHA-256 du jeton est persisté. Les opérations `approve`, `reject` et
`revise` hachent l'entrée, effectuent une comparaison en temps constant, appliquent
un contrôle optimiste de version puis retirent l'empreinte consommée. La transition
et son audit partagent la même transaction PostgreSQL.

Les en-têtes `X-Tenant-ID` et `X-User-ID` sont uniquement un adaptateur de
développement, pas une authentification. Ils sont interdits en production. Chaque
lecture et écriture persistante est filtrée par tenant ; une proposition exige une
conversation appartenant au même tenant et au même utilisateur.

## Tests d'intégration PostgreSQL

La suite `integration` est ignorée tant que
`PKA_REPOSITORY_BACKEND` n'est pas explicitement égal à `postgres`. Elle doit être
exécutée contre une base de test migrée, accessible au runner et configurée avec les
variables séparées ci-dessus :

```powershell
$env:PKA_ENVIRONMENT = "test"
$env:PKA_REPOSITORY_BACKEND = "postgres"
$env:PKA_DATABASE_HOST = "postgres.test.internal"
$env:PKA_DATABASE_PORT = "5432"
$env:PKA_DATABASE_NAME = "pka_integration"
$env:PKA_DATABASE_USER = "pka_integration"
$env:PKA_DATABASE_PASSWORD_FILE = "C:\run\secrets\postgres_password"
.venv\Scripts\python -m pytest -m integration
```

Le runner Compose/CI doit rejoindre le réseau de données sans publier PostgreSQL
sur Internet. La suite vérifie la révision Alembic, l'extension `vector` lorsque le
catalogue est accessible, les round-trips et audits, l'absence de jeton brut,
l'isolation tenant/utilisateur, la persistance après reconstruction, le CAS et le
rollback transactionnel. Elle écrit uniquement des données synthétiques avec des
identifiants uniques et ne supprime aucune donnée ni aucun volume.

## Lectures MCP distantes

Le backend expose `POST /api/mcp/reads`, avec un maximum de trois appels par requête.
Tous les appels d'un même batch doivent viser le même `source_system` ; les batches
multi-sources sont refusés par validation avant tout workflow ou accès réseau.
Le workflow est strictement en lecture seule et refuse avant tout accès réseau :

- un fournisseur ou binding désactivé ;
- un outil absent du registre local ;
- toute classe d'action autre que `READ` ;
- tout argument hors schéma, dont endpoint, tenant, utilisateur, `cloudId`,
  `fileKey` ou `nodeId` injecté par l'appelant ;
- un outil annoncé par `tools/list` dont le schéma d'entrée ou de sortie ne
  correspond pas à l'empreinte SHA-256 approuvée.

Aucun output schema fournisseur n'est encore approuvé dans ce contract pack. En
conséquence, chaque outil exige actuellement que `tools/list.outputSchema` et
`structuredContent` soient tous deux absents. Leur présence place la réponse en
quarantaine ; aucun schéma générique permissif n'est utilisé.

Les endpoints MCP, les origines source et la cible Figma sont des constantes de
code non configurables :

```text
Atlassian MCP  https://mcp.atlassian.com/v1/mcp
Figma MCP      https://mcp.figma.com/mcp
Jira           https://andrianalyfanny-1786296714755.atlassian.net
Confluence     https://andrianalyfanny.atlassian.net
Figma file     Ie3SsqL1KetjinTDHcNm2D
Figma node     36:114
```

Le transport utilise le SDK Python MCP `2.0.0` épinglé et Streamable HTTP. Les redirections,
le proxy issu de l'environnement, les retries et le cache de découverte sont
désactivés. Le délai de connexion est de trois secondes et le budget global de
trente secondes couvre connexion, `tools/list` et `tools/call`. Le client envoie
`Accept-Encoding: identity` et refuse toute réponse compressée. Une réponse est
limitée à 2 Mio de texte/JSON et 8 Mio d'image.
Les liens de ressource, ressources embarquées, contenus audio et MIME image non
approuvés sont refusés ; aucune URL retournée n'est téléchargée. Ce contract pack
n'accepte que le protocole MCP `2026-07-28` ; toute autre version négociée est
refusée avant la découverte des outils.

### Configuration MCP

Tous les kill switches sont désactivés par défaut :

- `PKA_MCP_READS_ENABLED=false` ;
- `PKA_MCP_MUTATIONS_ENABLED=false`, seule valeur acceptée par cette version ;
- `PKA_MCP_ATLASSIAN_ENABLED=false` ;
- `PKA_MCP_JIRA_ENABLED=false` ;
- `PKA_MCP_CONFLUENCE_ENABLED=false` ;
- `PKA_MCP_FIGMA_ENABLED=false` ;
- `PKA_MCP_GRANT_BACKEND=disabled`.

Jira et Confluence sont deux bindings distincts. Leur activation exige un UUID
stocké côté serveur dans `PKA_MCP_ATLASSIAN_JIRA_CLOUD_ID` ou
`PKA_MCP_ATLASSIAN_CONFLUENCE_CLOUD_ID`. Le LLM et l'API ne peuvent pas fournir ces
identifiants. Lorsque les deux bindings sont activés, leurs UUID doivent être
distincts puisque les origines Jira et Confluence sont différentes.

`PKA_MCP_READS_ENABLED=true` exige `PKA_REPOSITORY_BACKEND=postgres`. Avant chaque
ouverture de transport, le backend persiste de façon autonome et append-only un
événement `MCP_READ_AUTHORIZED` dans une transaction courte. Il persiste ensuite
`MCP_READ_COMPLETED` ou `MCP_READ_FAILED`, sans conserver le contenu, les arguments,
JQL/CQL ni bearer. Seuls les identifiants de contexte, métadonnées de contrat,
empreintes d'arguments/binding, version protocolaire et code d'erreur sûr sont
écrits. Un échec d'audit pré-appel interdit le réseau ; un échec d'audit final
retient le résultat et renvoie une erreur expurgée. Aucune transaction SQL ne reste
ouverte pendant l'appel réseau.

Le port de grant délégué reste opaque au workflow. Aucun flux OAuth web n'est
improvisé dans ce lot. Pour le développement et les tests uniquement,
`PKA_MCP_GRANT_BACKEND=development_files` autorise un bearer monté dans un fichier.
Le fichier est relu à chaque connexion et doit être lié à l'identité exacte :

```text
PKA_MCP_ATLASSIAN_BEARER_TOKEN_FILE
PKA_MCP_ATLASSIAN_GRANT_TENANT_ID
PKA_MCP_ATLASSIAN_GRANT_USER_ID

PKA_MCP_FIGMA_BEARER_TOKEN_FILE
PKA_MCP_FIGMA_GRANT_TENANT_ID
PKA_MCP_FIGMA_GRANT_USER_ID
```

Ces variables doivent être absentes du Compose de base. Un override privé monte le
fichier secret et ajoute les bindings lors d'une activation locale. Une chaîne vide
n'est pas équivalente à une valeur absente. Le backend refuse ce mode et tout chemin
de bearer en production. Il ne persiste, ne retourne et ne journalise aucun token.

Le résultat API normalisé attribue chaque lecture au fournisseur, système source,
origine, outil, version protocolaire, empreinte de schéma, hash des arguments,
empreinte du binding, politique et corrélation. Les payloads et contenus source ne
sont pas journalisés.

`resource_reference` est **dérivé, jamais observé** : il est construit côté serveur à
partir de l'origine constante du contrat et d'un argument public déjà validé par
JSON-Schema, percent-encodé sans caractère sûr afin qu'une valeur ne puisse pas sortir
de son segment de chemin. Aucune donnée de la réponse fournisseur n'y entre, donc un
serveur compromis ne peut pas rediriger une citation. Seuls les contrats portant un
identifiant de ressource requis en fournissent un ; les autres retournent `null`.

`source_complete` reste `false` en toutes circonstances : tant qu'un output schema
authentifié n'atteste pas l'intégralité du corps, le résultat identifie sa ressource
mais ne doit pas être présenté comme une citation source complète.

### Limites MCP actuelles

Le registre bloque volontairement tout appel si un fournisseur modifie le schéma
annoncé. Une nouvelle empreinte doit être capturée avec un grant de sandbox, revue,
puis mise à jour dans le contract pack avant réactivation. La compatibilité réelle
du client backend personnalisé avec le catalogue Figma et les deux `cloudId`
Atlassian restent à valider dans l'environnement pilote.

Le transport réalise, avant acquisition du grant, une résolution DNS des hostnames
fixes et refuse l'ensemble de la réponse si une adresse est privée, loopback,
link-local, multicast, non spécifiée, non globale ou assimilable à un endpoint de
métadonnées. Ce préflight ne lie toutefois pas l'adresse vérifiée à la connexion
TLS ultérieure et ne suffit donc pas contre un DNS rebinding entre les deux étapes.
L'activation réelle reste **NO-GO** sans pare-feu/proxy egress imposant la même
allowlist d'hôtes et bloquant les plages non publiques au niveau réseau.

Le grant de développement Atlassian reste, conformément au contrat pilote, lié au
provider, tenant et utilisateur et non cryptographiquement à un seul site. Les
`cloudId` injectés limitent la cible applicative, mais une activation pilote doit
également vérifier côté broker OAuth que la délégation utilisateur couvre seulement
les sites attendus.

Aucune mutation MCP n'est câblée dans la racine de composition.
`ApprovedMutationRunner` reste inactif. Les endpoints d'approbation ne déclenchent
donc aucune écriture Jira, Confluence ou Figma. L'activation future reste bloquée
tant que l'identité déléguée de production, la revalidation des permissions,
l'idempotence persistante, l'outbox/réconciliation, les kill switches et l'audit
durable complet ne sont pas intégrés et validés.

Le mode `dev_headers`, les comptes de service et tout contournement du workflow
d'approbation restent interdits en production.

## Organisation

Les domaines `approvals`, `conversations`, `agent`, `mcp`, `knowledge` et `audit`
séparent modèles, ports, workflows et adaptateurs. `app/bootstrap.py` est l'unique
racine de composition ; les SDK et détails SQLAlchemy restent dans leurs
adaptateurs.
