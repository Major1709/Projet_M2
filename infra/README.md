# Infrastructure du MVP

Ce dossier decrit le premier deploiement de la plateforme : frontend Next.js, API FastAPI, worker Celery, PostgreSQL avec pgvector et Redis. Jira, Confluence et Figma restent accessibles par des serveurs MCP distants ; Groq reste un service externe. Neo4j, MinIO et une pile d'observabilite locale ne font pas partie du premier increment.

Le fichier `compose.yaml` est un contrat d'integration. Le parcours backend pris en
charge dans cet increment est `postgres -> migrate -> api`. Le service `worker`
reste un contrat reserve a l'increment asynchrone : Celery et son point d'entree ne
sont pas encore livres et ce service ne doit pas etre demarre.

## Topologie

```text
Navigateur -> frontend/BFF -> api -> PostgreSQL/pgvector
                              |  -> Redis <- worker
                              |
                              +  -> Groq et MCP via reseau egress
```

- `edge` relie le frontend et l'API. Seuls leurs ports sont publies, sur `127.0.0.1` par defaut.
- `data` est un reseau interne sans sortie Internet pour PostgreSQL et Redis.
- `egress` donne a l'API et au worker un chemin sortant. Compose ne filtre pas les domaines : en preproduction/production, un pare-feu ou proxy doit limiter la sortie aux endpoints Groq, OIDC et MCP approuves.
- PostgreSQL et Redis ne publient aucun port hote.
- La lecture MCP globale, les fournisseurs et chaque binding sont desactives par
  defaut (`default deny`). Les mutations MCP sont forcees a `false` dans Compose
  et une valeur `true` est aussi refusee par le backend.

## Pre-requis des scaffolds

Le Compose attend les fichiers et conventions suivants :

```text
frontend/Dockerfile
  - image de production Next.js
  - ecoute sur 0.0.0.0:3000
  - route GET /api/health
  - lecture serveur de API_INTERNAL_URL et des variables *_FILE

backend/Dockerfile
  - image Python commune a api, worker et migrate
  - CMD par defaut lancant FastAPI sur 0.0.0.0:8000
  - executable alembic et fichier alembic.ini
  - route GET /health/ready qui verifie PostgreSQL
  - lecture des secrets *_FILE avant construction des clients
```

L'API et Alembic construisent la meme URL SQLAlchemy depuis
`PKA_DATABASE_HOST`, `PKA_DATABASE_PORT`, `PKA_DATABASE_NAME`,
`PKA_DATABASE_USER` et `PKA_DATABASE_PASSWORD_FILE`. Les reglages de pool sont
`PKA_DATABASE_POOL_SIZE` et `PKA_DATABASE_MAX_OVERFLOW`. Le mot de passe reste
dans le fichier monte sous `/run/secrets` ; l'URL complete ne doit jamais etre
ecrite dans les logs. PostgreSQL reste accessible uniquement depuis le reseau
Compose `data` et ne publie pas de port sur l'hote.

## Demarrage local

1. Copier `infra/.env.example` vers `infra/.env` et conserver ce dernier hors Git.
2. Creer `infra/secrets/dev/` et `infra/backups/`.
3. Creer un fichier d'une seule ligne pour chacun des secrets suivants :

   - `postgres_password` ;
   - `redis_password` ;
   - `groq_api_key` ;
   - `token_encryption_key` ;
   - `session_signing_key` ;
   - `oidc_client_secret`.

   Utiliser des valeurs aleatoires distinctes. Ne jamais copier leur contenu dans `.env`, les logs, une image ou un prompt. Les fichiers sont ignores par `infra/.gitignore`.

4. Valider la configuration sans afficher l'environnement resolu :

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml config --quiet
```

5. Construire l'image backend, puis lancer PostgreSQL et attendre son healthcheck :

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml build api migrate
docker compose --env-file infra/.env -f infra/compose.yaml up -d --wait postgres
docker compose --env-file infra/.env -f infra/compose.yaml ps postgres
```

6. Appliquer les migrations avant de demarrer une nouvelle version applicative :

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml --profile ops run --rm migrate
```

7. Verifier la revision Alembic et l'extension `vector` sans afficher de secret :

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml --profile ops run --rm migrate python -m alembic current
docker compose --env-file infra/.env -f infra/compose.yaml exec -T postgres sh -lc 'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --tuples-only --no-align --command="SELECT version_num FROM alembic_version;"'
docker compose --env-file infra/.env -f infra/compose.yaml exec -T postgres sh -lc 'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --tuples-only --no-align --command="SELECT extname, extversion FROM pg_extension ORDER BY extname;"'
```

8. Lancer l'API. Redis est demarre automatiquement comme dependance Compose,
   mais le worker reste hors tranche :

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml up -d --wait api
docker compose --env-file infra/.env -f infra/compose.yaml ps api postgres redis
Invoke-RestMethod http://localhost:8000/health/ready
docker compose --env-file infra/.env -f infra/compose.yaml logs --tail 100 api
```

Le port API `http://localhost:8000` est publie uniquement pour le diagnostic local.
Le navigateur devra normalement passer par le BFF et une origine unique lorsque
le parcours frontend sera lance.

Pour verifier la persistance, creer une conversation synthetique, conserver son
identifiant, recreer uniquement l'API, puis relire la conversation :

```powershell
$headers = @{ "X-Tenant-ID" = "qa-local"; "X-User-ID" = "qa-user" }
$body = @{ title = "Persistence smoke test" } | ConvertTo-Json
$created = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/conversations -Headers $headers -ContentType "application/json" -Body $body
docker compose --env-file infra/.env -f infra/compose.yaml up -d --force-recreate --wait api
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/conversations/$($created.id)" -Headers $headers
```

Ce test utilise exclusivement des identifiants synthetiques locaux. Il ne doit
jamais etre execute avec des donnees ou comptes de production.

Pour arreter sans supprimer les donnees :

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml down
```

Ne pas utiliser `down --volumes` en dehors d'une remise a zero explicitement autorisee : cela detruit les volumes PostgreSQL et Redis.

## Migrations

- Alembic est le proprietaire du schema PostgreSQL, y compris l'activation versionnee de l'extension `vector`.
- Une migration s'execute une seule fois par deploiement au moyen du service `migrate` du profil `ops`.
- Le service `migrate` reutilise le meme constructeur d'URL et la meme metadata SQLAlchemy que l'API ; `alembic.ini` ne contient aucune URL ni aucun secret.
- En production, le pipeline lance la migration comme job distinct avant la bascule du trafic.
- Utiliser des migrations compatibles avec l'ancienne et la nouvelle version (`expand/contract`) pour permettre un rollback applicatif.
- Toute migration destructive exige une sauvegarde verifiee, une fenetre approuvee et un plan de restauration. Une descente Alembic automatique n'est pas consideree comme un rollback fiable des donnees.

Avant une migration sur une base non ephemere :

1. verifier `docker compose ... config --quiet`, les versions d'images et l'espace disque ;
2. verifier que PostgreSQL est sain et qu'aucun autre job de migration n'est actif ;
3. consulter `python -m alembic current`, `heads` et `history` depuis le service `migrate` ;
4. produire et verifier une sauvegarde si la base contient deja des donnees ;
5. appliquer `upgrade head`, puis verifier la revision, l'extension `vector`, la readiness et le smoke test de persistance.

La migration initiale est additive : elle active `vector` si necessaire puis cree
les tables de conversations, propositions d'action et audit. Elle ne cree ni
outbox, ni stockage d'idempotence, ni utilisateurs, ni tables RAG. Elle ne stocke
jamais le `decision_token` brut, uniquement son empreinte nullable.

## Sauvegarde et restauration

PostgreSQL contient les conversations, approbations, audits applicatifs, liaisons et index RAG. Redis est un broker/cache reprenable et ne doit jamais etre l'unique stockage d'un workflow ou d'une intention de mutation.

Pour produire un dump logique manuel horodate et son SHA-256 :

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml --profile ops run --rm postgres-backup
```

Le dump est ecrit dans `infra/backups/`. Il doit ensuite etre chiffre et copie hors de l'hote. Ne pas conserver une cle de chiffrement avec la sauvegarde.

Baseline provisoire a faire valider avant production :

- sauvegarde PostgreSQL chiffree quotidienne et avant migration a risque ;
- conservation de 7 sauvegardes quotidiennes et 4 hebdomadaires ;
- test de restauration mensuel dans un environnement isole ;
- PostgreSQL manage avec sauvegardes continues/PITR pour la production ;
- export regulier du journal d'audit vers un stockage append-only/WORM ;
- RPO/RTO definitifs fixes apres connaissance des volumes et obligations metier.

Procedure minimale de restauration : isoler l'environnement cible, verifier le checksum et dechiffrer le dump hors du depot, provisionner une base vide compatible, executer `pg_restore`, verifier les migrations et les invariants d'audit, puis effectuer les smoke tests. Les connexions MCP et mutations restent coupees jusqu'a revalidation des grants et permissions. La restauration est une operation destructive sur la base cible et doit etre approuvee ; aucun service de restauration automatique n'est fourni dans Compose.

## Secrets

Les fichiers locaux sous `infra/secrets/` servent uniquement au developpement. Les applications recoivent leurs chemins `/run/secrets/...`, jamais les valeurs dans des variables versionnees.

En preproduction et production :

- utiliser un coffre de secrets et une identite de workload ;
- monter ou injecter les secrets a l'execution avec separation par environnement ;
- chiffrer les refresh tokens par enveloppe avec une cle KMS/HSM ;
- faire tourner les cles et grants, avec revocation documentee ;
- ne mettre dans les variables d'environnement que des references au coffre ;
- scanner images, logs, traces et sauvegardes pour les secrets.

Les grants OAuth MCP sont des jetons utilisateur et ne doivent jamais devenir une
valeur d'environnement, un argument de CLI, une ligne de log ou un exemple. Le
Compose de base ne declare ni leur secret ni leur chemin : il reste donc valide
et demarrable quand les fichiers de grants n'existent pas. L'activation locale
ajoute les montages et les variables `*_BEARER_TOKEN_FILE` avec un override prive,
uniquement apres les controles ci-dessous.

## MCP en lecture seule

Les destinations sont des constantes du backend et ne sont pas surchargeables par
l'environnement :

| Binding | Endpoint MCP | Source ou cible admise |
|---|---|---|
| Jira | `https://mcp.atlassian.com/v1/mcp` | `https://andrianalyfanny-1786296714755.atlassian.net` et son `cloudId` |
| Confluence | `https://mcp.atlassian.com/v1/mcp` | `https://andrianalyfanny.atlassian.net` et son `cloudId` distinct |
| Figma | `https://api.figma.com` (REST, pas MCP) | `https://www.figma.com`, tout fichier couvert par le jeton |

Jira et Confluence partagent le serveur Atlassian, mais leurs bindings, `cloudId`
et kill switches restent distincts. Aucun endpoint, domaine source ni `cloudId`
fourni par une requete, un contenu recupere ou une variable d'environnement ne
doit les remplacer.

Le `fileKey` Figma fait exception et n'est pas epingle : il est fourni par
l'appelant et valide sur sa forme seule, parce que l'assistant doit lire les
fichiers de process de tout l'espace couvert par le jeton. Ce jeton est donc la
frontiere : pour restreindre ce qui est lisible, restreindre le compte qui le
porte, pas la configuration.

Le demarrage par defaut injecte les gardes suivantes :

```text
PKA_MCP_READS_ENABLED=false
PKA_MCP_ATLASSIAN_ENABLED=false
PKA_MCP_JIRA_ENABLED=false
PKA_MCP_CONFLUENCE_ENABLED=false
PKA_MCP_FIGMA_ENABLED=false
PKA_MCP_GRANT_BACKEND=disabled
PKA_MCP_MUTATIONS_ENABLED=false  # valeur imposee par Compose
```

Une lecture Jira ou Confluence exige simultanement la garde globale, la garde
Atlassian et la garde du binding concerne. Une lecture Figma exige la garde globale
et la garde Figma. Une garde manquante refuse l'appel.

### Conditions bloquantes avant activation

L'activation reste **NO-GO** tant que toutes les preuves applicables ne sont pas
jointes au compte rendu d'admission :

1. grant OAuth d'un compte sandbox a privileges minimaux, lie au tenant et a
   l'utilisateur attendus, stocke dans un fichier secret monte et revocable ;
2. `cloudId` Jira et/ou Confluence verifie pour la source fixe, avec deux bindings
   distincts et sans jamais afficher le token utilise pour la verification ;
3. contract pack approuve pour l'endpoint exact : transport, outils de lecture,
   schemas et empreintes, allowlist `default deny`, timeouts, quotas, erreurs et
   tests prouvant que toute mutation ou tout outil inconnu est refuse ;
4. pour Figma, admission explicite du fichier et du noeud fixes, validation des
   droits reels de lecture et du schema des outils exposes ;
5. filtrage egress, redaction des journaux, alertes et procedure de revocation
   testes dans l'environnement autorise.

`development_files` est le seul backend de grants utilisable avec Compose local ;
il est interdit hors `development` et `test`. Aucun compte ou donnees de production
ne doit etre utilise.

### Montage local apres admission

Creer les deux fichiers d'une seule ligne sous `infra/secrets/dev/` seulement pour
les fournisseurs admis, sans jamais en afficher le contenu :
`mcp_atlassian_bearer_token` et `mcp_figma_bearer_token`. Ils sont ignores par Git
et ne doivent pas etre copies dans une image. Ne pas les creer avant l'admission.

Conserver ensuite l'override suivant hors du depot, en supprimant le fournisseur
qui n'est pas admis et le `cloudId` de tout binding Atlassian laisse desactive. Les
bindings non secrets sont lus depuis `infra/.env`, jamais depuis une requete
utilisateur :

```yaml
services:
  api:
    environment:
      PKA_MCP_GRANT_BACKEND: development_files
      PKA_MCP_ATLASSIAN_BEARER_TOKEN_FILE: /run/secrets/mcp_atlassian_bearer_token
      PKA_MCP_ATLASSIAN_GRANT_TENANT_ID: ${PKA_MCP_ATLASSIAN_GRANT_TENANT_ID:?required}
      PKA_MCP_ATLASSIAN_GRANT_USER_ID: ${PKA_MCP_ATLASSIAN_GRANT_USER_ID:?required}
      PKA_MCP_ATLASSIAN_JIRA_CLOUD_ID: ${PKA_MCP_ATLASSIAN_JIRA_CLOUD_ID:?required}
      PKA_MCP_ATLASSIAN_CONFLUENCE_CLOUD_ID: ${PKA_MCP_ATLASSIAN_CONFLUENCE_CLOUD_ID:?required}
      PKA_MCP_FIGMA_BEARER_TOKEN_FILE: /run/secrets/mcp_figma_bearer_token
      PKA_MCP_FIGMA_GRANT_TENANT_ID: ${PKA_MCP_FIGMA_GRANT_TENANT_ID:?required}
      PKA_MCP_FIGMA_GRANT_USER_ID: ${PKA_MCP_FIGMA_GRANT_USER_ID:?required}
    secrets:
      - mcp_atlassian_bearer_token
      - mcp_figma_bearer_token

secrets:
  mcp_atlassian_bearer_token:
    file: ${SECRETS_DIR:-./secrets/dev}/mcp_atlassian_bearer_token
  mcp_figma_bearer_token:
    file: ${SECRETS_DIR:-./secrets/dev}/mcp_figma_bearer_token
```

Valider l'assemblage avec `config --quiet` seulement :

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml -f C:\pka-private\compose.mcp-grants.yaml config --quiet
```

Ne jamais utiliser `docker compose config` sans `--quiet`,
`docker compose exec env`, `set`, `Get-ChildItem Env:` ou une commande contenant
un token. Apres validation et autorisation de l'environnement de test, activer dans
`infra/.env` uniquement les gardes du fournisseur admis, puis recreer l'API sans
construction implicite :

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml -f C:\pka-private\compose.mcp-grants.yaml up -d --no-build --no-deps --force-recreate api
```

Le worker reste hors tranche ; lorsqu'il sera admis, il devra recevoir exactement
les memes montages et bindings.

### Coupure et retour arriere MCP

En incident, arreter d'abord `api` (et `worker` s'il existe) pour couper l'egress
immediatement :

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml stop api worker
```

Passer ensuite toutes les variables `PKA_MCP_*_ENABLED` a `false`, remettre
`PKA_MCP_GRANT_BACKEND=disabled`, retirer l'override de grants et recreer uniquement
l'API sur la configuration de base :

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml up -d --no-build --no-deps --force-recreate api
```

Revoquer les grants cote fournisseur par le canal d'administration autorise,
conserver les preuves redactees, puis verifier la readiness et l'absence d'appels
MCP. Cette procedure ne modifie ni PostgreSQL ni ses volumes et ne requiert aucune
migration.

## Observabilite

Les conteneurs ecrivent des logs structures sur stdout/stderr avec rotation locale. Les champs minimum attendus sont `timestamp`, `level`, `service`, `environment`, `trace_id`, `correlation_id`, `tenant_id` pseudonymise, `workflow_id`, `action_id`, `tool_id` et un code d'erreur normalise. Les tokens, cookies, en-tetes d'autorisation, prompts bruts et contenus sensibles sont expurges avant emission.

L'API et le worker doivent etre instrumentes avec OpenTelemetry. `OTEL_SDK_DISABLED=true` garde l'export coupe tant qu'un collecteur n'est pas provisionne. Pour la production, exporter vers une plateforme geree ou un collecteur separe et surveiller au minimum :

- latence, debit et taux d'erreur HTTP/SSE ;
- saturation du pool PostgreSQL, taille de base et echecs de migration ;
- profondeur, age et taux d'echec/retry des files Celery ;
- disponibilite et latence Redis ;
- latence, erreurs, timeouts et circuit breakers par MCP ;
- appels/tokens/latence Groq et budgets par tenant, sans contenu de prompt ;
- refus de permission, outils inconnus, injections detectees et activation des kill switches ;
- propositions en attente, expirees, partielles ou en reconciliation ;
- continuite de la chaine d'audit et age de la derniere sauvegarde restauree.

Alertes minimales : mutations sans evenement d'audit complet, erreurs inter-tenant, outil/schema inconnu, file bloquee, taux d'erreur MCP eleve, base presque pleine, sauvegarde absente et tentative repetee de contournement d'approbation.

## Environnements et promotion

| Environnement | Donnees | Execution | Secrets |
|---|---|---|---|
| Local | fixtures et comptes sandbox | Docker Compose | fichiers ignores par Git |
| CI | donnees ephemeres synthetiques | Compose avec projet unique par job | secrets temporaires/canary |
| Integration | tenants Jira/Confluence/Figma sandbox | images du registre | coffre non-production |
| Preproduction | donnees anonymisees ou sandbox realiste | meme topologie logique que production | coffre et identites dedies |
| Production | donnees autorisees | images immuables, DB/Redis manages, ingress TLS | coffre/KMS/HSM |

Une image est construite une fois, scannee, signee et promue par digest. La configuration et les comptes sont distincts par environnement. Les mutations restent desactivees jusqu'a validation des exigences `SEC-*`, des MCP exacts et de la matrice de permissions reelle.

Plan de deploiement :

1. valider configuration, versions d'images, schemas MCP allowlistes et kill switches ;
2. verifier sauvegarde/restauration et capacite disponible ;
3. appliquer les migrations compatibles ;
4. deployer API et worker avec mutations coupees ;
5. executer healthchecks et smoke tests de lecture/RAG ;
6. deployer le frontend et verifier session, SSE, citations et approbations sans execution ;
7. activer progressivement les MCP de lecture par tenant pilote apres les preuves
   OAuth, `cloudId`, contract pack et admission Figma applicables ;
8. conserver `PKA_MCP_MUTATIONS_ENABLED=false` : les mutations sont hors de ce lot
   et ne disposent d'aucune procedure d'activation ;
9. observer les indicateurs et conserver une fenetre de rollback.

## Runbook minimal

### Service indisponible

1. Consulter `docker compose ... ps` puis les logs du service, par `correlation_id`.
2. Verifier l'etat PostgreSQL/Redis, l'espace disque, la file Celery et la derniere migration.
3. Si une source externe est indisponible, ouvrir le circuit correspondant et ne jamais presenter une mutation comme reussie.
4. Redemarrer uniquement le service concerne apres capture des diagnostics.

### Suspicion de fuite, token ou MCP compromis

1. Arreter `api` et `worker` s'il est actif pour couper immediatement l'egress MCP.
2. Passer toutes les gardes `PKA_MCP_*_ENABLED=false`, remettre
   `PKA_MCP_GRANT_BACKEND=disabled`, retirer l'override de grants, puis recreer
   uniquement les services autorises.
3. Revoquer les grants/sessions concernes et effectuer la rotation des secrets.
4. Isoler les chunks RAG suspects et conserver les preuves/audits redactes.
5. Identifier les actions par `trace_id`, `action_id` et cle d'idempotence.
6. Ne reactiver qu'apres correction, rotation, reindexation necessaire et tests de securite.

### Execution au resultat ambigu

1. Placer l'action en `UNKNOWN_RECONCILIATION_REQUIRED`.
2. Suspendre tout retry automatique.
3. Rechercher l'objet cote source avec la correlation/idempotence approuvee.
4. Renseigner le resultat reel et reprendre uniquement les sous-actions non executees.

### Rollback

- Arreter le deploiement de la nouvelle API et conserver PostgreSQL ainsi que ses volumes en place.
- Revenir au digest applicatif precedent si les migrations additives restent compatibles.
- Ne pas lancer de migration descendante : la revision initiale refuse explicitement le downgrade destructif.
- Une extension ou une table additive inutilisee peut rester en place pendant l'analyse ; ne pas la supprimer en urgence.
- Si les donnees sont alterees, isoler le trafic, obtenir l'approbation de restauration, restaurer dans une base controlee et reconcilier les actions externes ; un rollback local ne peut pas annuler automatiquement une mutation deja reussie dans Jira, Confluence ou Figma.

## Limites connues du squelette

- Le worker Celery et son point d'entree ne sont pas disponibles dans cette tranche ; ne pas demarrer le service `worker`.
- Le parcours frontend complet et les connecteurs externes ne font pas partie de cette validation PostgreSQL.
- Les versions/digests d'images devront etre pinnees et verifiees avant un deploiement partage.
- Les endpoints MCP et les cibles de ce lot sont fixes. Les audiences OAuth,
  contract packs, `cloudId`, grants utilisateur et preuves d'admission restent a
  qualifier avant toute activation.
- Compose ne fournit ni TLS, ni filtrage egress par domaine, ni haute disponibilite, ni stockage WORM.
- Les SLO, RPO/RTO, volumetries, retention et residence des donnees restent a valider.
- Le chargement local de `BAAI/bge-m3` suppose que l'image worker embarque le modele ou qu'un service d'embeddings soit defini ulterieurement ; aucun telechargement implicite n'est declenche ici.
