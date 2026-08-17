# CHAT-BE-PG-001 — Persistance PostgreSQL du backend

## Exécution

- Déclencheur : ordre explicite dans le chat
- Taille : M
- Run ID : `4a0a9e93-390a-4e5a-aa78-4b3142602272`
- Branche : `feature/backend-postgres`
- Commit fonctionnel : `77e78f8`
- Statut : `QA Approved`

## Objectif et résultat

Le backend FastAPI utilise désormais PostgreSQL/pgvector fourni par Docker Compose quand
`PKA_REPOSITORY_BACKEND=postgres`. Les conversations, propositions d'approbation et événements
d'audit disposent d'adaptateurs SQLAlchemy synchrones, de migrations Alembic et d'une persistance
tenant-aware.

Les transitions d'approbation et leurs audits partagent une transaction. Le contrôle optimiste
repose sur un compare-and-swap de version. Le jeton de décision brut est remis une seule fois ;
seul son SHA-256 est persisté, puis supprimé lors de sa consommation.

La readiness vérifie PostgreSQL et renvoie une erreur générique `503` dans un budget inférieur à
trois secondes lorsque la base est indisponible. La liveness reste indépendante.

## Rôles mobilisés

- Architecte / Tech Lead : cadrage, contrats, branche, intégration et journal
- Backend : configuration, schéma, adaptateurs, UoW, API et tests
- DevOps / SRE : Dockerfile, Compose, Alembic, migration et runbook
- MCP / IAM / Sécurité : contrat du token one-time et revue finale
- QA / Test Automation : plan P0, campagne PostgreSQL réelle et verdict indépendant

## Fichiers et modules principaux

- `backend/app/core/` : configuration et moteur SQLAlchemy
- `backend/app/persistence/` : metadata et erreurs de mapping
- `backend/app/*/adapters/postgres.py` : conversations, approbations et audit
- `backend/app/bootstrap.py`, `backend/app/main.py`, `backend/app/health/api.py`
- `backend/migrations/` et `backend/alembic.ini`
- `backend/Dockerfile`
- `backend/tests/`
- `backend/README.md`
- `infra/compose.yaml`, `infra/.env.example`, `infra/README.md`

## Vérifications et preuves

- Pytest hors PostgreSQL : `18 passed, 5 skipped`
- Pytest PostgreSQL réel : `5 passed`
- Ruff sur application, tests et migrations : succès
- `docker compose ... config --quiet` : succès
- Alembic : révision `20260811_0001 (head)`, deuxième upgrade idempotent
- Extension PostgreSQL `vector` : présente
- Persistance après reconstruction du conteneur applicatif : succès
- Isolation tenant/utilisateur : accès adverses en `404`
- CAS concurrent : un succès et un conflit, un seul audit
- Panne PostgreSQL : liveness `200`, readiness `503` en `2078 ms`
- Reprise PostgreSQL : readiness `200` en `436 ms`
- Revue Sécurité finale : GO pour la persistance de développement
- Verdict QA final : PASS

## Documentation

`backend/README.md` et `infra/README.md` documentent les variables, secrets par fichier, migrations,
commandes Docker, readiness, tests et procédure de retour arrière non destructive.

## Limites et risques connus

- Le build de l'image backend n'a pas abouti dans cette session : Docker Desktop/Buildx est resté
  bloqué sans sortie malgré plusieurs tentatives. Le Dockerfile et le Compose ont été validés
  statiquement, mais la construction d'image reste à rejouer sur un daemon Docker opérationnel.
- L'autorisation concerne le développement local, pas la production.
- Les mutations MCP restent NO-GO : OIDC/CSRF, expiration des approbations, rôles DB séparés,
  audit WORM, limites JSON, outbox, idempotence et revalidation source restent à livrer.
- Les données synthétiques QA sont conservées dans leur volume dédié ; aucun volume n'a été supprimé.
- L'intégration Notion n'était pas disponible ; ce journal local devra être synchronisé dans le
  Development Log Notion quand l'intégration sera rétablie.

## Livraison

- Pull request : non créée
- Fusion dans `main` : non effectuée
- Déploiement : non effectué

