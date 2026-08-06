# Backend du Project Knowledge Assistant

Scaffold FastAPI du monolithe modulaire qui orchestre Groq et les serveurs MCP Jira, Confluence et Figma. Aucun connecteur externe ni SDK Groq n'est appelé dans cet incrément.

## Démarrage local

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn app.main:app --reload
```

Tests :

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check app tests
```

## API disponible

- `GET /health`, `GET /health/live` et `GET /health/ready` : état du processus API.
- `POST /api/conversations` et `GET /api/conversations/{id}` : création et lecture d'une conversation.
- `POST /api/actions` et `GET /api/actions/{id}` : création et lecture d'une proposition de mutation.
- `POST /api/actions/{id}/approve` : approbation optimiste avec `expected_version` et `decision_token`.
- `POST /api/actions/{id}/reject` : rejet avec les mêmes protections anti-rejeu.
- `POST /api/actions/{id}/revise` : rend la proposition courante `SUPERSEDED` et crée un nouveau snapshot `PENDING_APPROVAL`.

Chaque proposition conserve un snapshot JSON canonique et son SHA-256. Une révision ne modifie jamais ce snapshot. Les transitions utilisent une version optimiste atomique dans le repository.

## Invariant de sécurité

`ApprovedMutationRunner` est l'unique façade prévue pour les mutations MCP. Elle refuse tout appel si la proposition n'est pas exactement dans l'état `APPROVED`, puis impose une réautorisation avant de déléguer au gateway. Les interfaces `LLMProvider` et `MCPToolGateway` ne contiennent aucune implémentation réseau.

Le endpoint d'approbation **n'exécute pas** la mutation. L'exécution asynchrone et sa reprise seront branchées ultérieurement sur la façade gardée.

## Limites volontaires du scaffold

- Le `InMemoryActionProposalRepository`, le repository de conversations et le sink d'audit mémoire sont réservés au développement et perdent les données au redémarrage.
- L'identité est injectée temporairement via `X-Tenant-ID` et `X-User-ID`. Ces en-têtes ne sont pas une authentification et le mode `dev_headers` est refusé en production.
- Les tokens OAuth, la délégation d'identité, le stockage PostgreSQL, les transactions durables, l'outbox, l'idempotence persistante et la réautorisation réelle des sources sont des TODO bloquants avant toute intégration MCP.
- Le `decision_token` est une protection anti-rejeu de développement. En production il devra être stocké sous forme de hash, expirer, être lié à la session authentifiée et ne jamais apparaître dans les logs.
- Les payloads complets ne sont pas envoyés dans l'audit mémoire ; seul leur hash est conservé.

## Variables de configuration

Préfixe `PKA_` :

- `PKA_ENVIRONMENT` : `development`, `test` ou `production`.
- `PKA_REPOSITORY_BACKEND` : seul `memory` existe dans ce scaffold.
- `PKA_AUTH_MODE` : seul `dev_headers` existe dans ce scaffold.

Le démarrage échoue en `production` tant que le repository mémoire ou l'authentification par en-têtes sont actifs.

## Organisation

Chaque capacité métier (`approvals`, `conversations`, `knowledge`, `mcp`, `agent`, `audit`) possède sa propre interface publique. Les modèles sont dans `domain.py`, les interfaces externes dans `ports.py`, les cas d'usage dans `workflow.py`, les adaptateurs HTTP dans `api.py` et les implémentations concrètes dans `adapters/`.

`app/bootstrap.py` est la racine de composition. `app/main.py` crée uniquement l'application et branche les routes. Voir `docs/architecture/code-organization.md` pour les règles de dépendance.
