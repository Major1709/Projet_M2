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

## Limites MCP actuelles

Aucune mutation MCP n'est câblée dans la racine de composition. Les endpoints
d'approbation ne déclenchent donc aucune écriture Jira, Confluence ou Figma.
L'activation future reste bloquée tant que l'identité déléguée, la revalidation des
permissions, l'idempotence persistante, l'outbox/réconciliation, le kill switch et
l'audit durable complet ne sont pas intégrés et validés.

Le mode `dev_headers`, les comptes de service non démontrés et tout contournement du
workflow d'approbation restent interdits en production.

## Organisation

Les domaines `approvals`, `conversations`, `agent`, `mcp`, `knowledge` et `audit`
séparent modèles, ports, workflows et adaptateurs. `app/bootstrap.py` est l'unique
racine de composition ; les SDK et détails SQLAlchemy restent dans leurs
adaptateurs.
