# Résumé du projet

## Objectif

Nous avons préparé la base d’un assistant web qui rassemble les connaissances de
Jira, Confluence et Figma. L’assistant doit pouvoir rechercher des informations,
répondre avec des sources et proposer des modifications. Une modification ne doit
jamais être exécutée sans validation humaine.

## Ce qui a été réalisé

### Interface web

- création d’une interface Next.js responsive ;
- affichage et sélection de demandes Jira fictives ;
- simulation de leur indexation ;
- chat de démonstration avec des références Jira, Confluence et Figma ;
- aperçu d’une proposition de modification Confluence ;
- actions pour approuver, modifier ou rejeter la proposition ;
- prise en charge du clavier, des lecteurs d’écran et de la réduction des animations.

### API backend

- création d’une API FastAPI organisée par fonctionnalités ;
- routes de santé pour vérifier que l’API fonctionne ;
- création et consultation de conversations ;
- création, consultation, approbation, rejet et révision de propositions ;
- protection contre une décision répétée ou basée sur une ancienne version ;
- conservation d’un hash du contenu approuvé ;
- blocage d’une mutation tant que la proposition n’est pas approuvée ;
- nouvelle vérification des permissions juste avant l’exécution.

### Architecture et sécurité

- définition de l’architecture générale du système ;
- conception de la recherche RAG et de la gestion des sources ;
- définition des contrats pour Groq et les connecteurs MCP ;
- séparation des responsabilités entre le frontend, le backend et les services externes ;
- règles de sécurité pour l’identité, les permissions, l’audit et les mutations.

### Infrastructure et qualité

- préparation d’un fichier Docker Compose pour le frontend, l’API, un worker,
  PostgreSQL/pgvector et Redis ;
- définition d’une stratégie de tests et de validation ;
- ajout de tests backend sur les conversations et le cycle d’approbation ;
- ajout de tests frontend sur l’indexation, le chat et les décisions.

## Fonctionnement actuel

Le parcours de démonstration est le suivant :

1. l’utilisateur sélectionne des demandes Jira ;
2. il lance une indexation simulée ;
3. il pose une question dans le chat ;
4. l’interface affiche une réponse et ses sources fictives ;
5. une modification Confluence est proposée ;
6. l’utilisateur peut l’approuver, demander une révision ou la rejeter.

Le frontend et le backend existent, mais ils ne sont pas encore connectés entre eux.
L’interface utilise des données fictives et l’API conserve ses données en mémoire.

## Organisation du projet

| Dossier | Contenu |
|---|---|
| `frontend/` | Interface Next.js et démonstration utilisateur |
| `backend/` | API FastAPI et règles d’approbation |
| `infra/` | Configuration Docker Compose prévue pour le MVP |
| `docs/` | Spécifications, architecture, sécurité et stratégie de tests |

## Démarrage local

### Frontend

Prérequis : Node.js 20 ou plus récent.

```powershell
cd frontend
npm install
npm run dev
```

Ouvrir ensuite `http://localhost:3000`.

### Backend

Prérequis : Python 3.11 ou plus récent.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn app.main:app --reload
```

L’API est disponible sur `http://localhost:8000`. Sa documentation interactive est
accessible sur `http://localhost:8000/docs`.

## Vérifications

Au 6 août 2026, les vérifications suivantes passent :

- 8 tests backend ;
- 4 tests frontend ;
- contrôle du code Python avec Ruff ;
- contrôle TypeScript et ESLint ;
- build de production Next.js.

```powershell
cd frontend
npm run test
npm run typecheck
npm run lint
npm run build

cd ..\backend
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check app tests
```

## Ce qui reste à faire

- connecter réellement le frontend à l’API ;
- ajouter l’authentification OIDC ;
- remplacer le stockage en mémoire par PostgreSQL ;
- implémenter le vrai parcours RAG et l’appel à Groq ;
- brancher les connecteurs Jira, Confluence et Figma ;
- ajouter le worker, les migrations et les Dockerfiles attendus par Docker Compose ;
- ajouter une intégration continue ;
- terminer les contrôles de sécurité avant d’autoriser une mutation réelle.

## État du projet

Le Sprint 0 est terminé : le cadrage, l’architecture, l’interface de démonstration,
le socle backend et les règles principales de sécurité sont en place. Le projet est
prêt pour un premier parcours réel en lecture seule, mais **pas encore pour exécuter
des modifications réelles dans Jira, Confluence ou Figma**.

Pour plus de détails, consulter :

- [`product/mvp-spec.md`](product/mvp-spec.md) pour les besoins fonctionnels ;
- [`architecture/system-architecture.md`](architecture/system-architecture.md) pour l’architecture ;
- [`security/backend-security-review.md`](security/backend-security-review.md) pour la sécurité ;
- [`qa/test-strategy.md`](qa/test-strategy.md) pour les tests.
