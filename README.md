# Project Knowledge Assistant

Assistant IA web pour exploiter les connaissances Jira, Confluence et Figma, avec Groq comme fournisseur LLM, recherche RAG hybride et approbation humaine obligatoire avant toute mutation.

Le contexte métier durable se trouve dans [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md). L'organisation technique et les règles de dépendance sont décrites dans [docs/architecture/code-organization.md](docs/architecture/code-organization.md).

Pour une présentation simple de ce qui a été réalisé, voir [docs/resume-du-projet.md](docs/resume-du-projet.md).

## Applications

- `backend/` : monolithe modulaire FastAPI et contrats des intégrations ;
- `infra/` : contrat Docker Compose des services actuellement exécutables ;
- `docs/` : produit, architecture, sécurité et stratégie QA.

Le frontend précédent a été retiré intentionnellement le 30 août 2026 afin de
repartir d'une implémentation neuve. Aucun dossier `frontend/` ni commande de
démarrage frontend ne fait partie de l'état courant du dépôt.

## Démarrage local

Backend :

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn app.main:app --reload
```

## Vérifications

```powershell
cd backend
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check app tests
```

Le nouveau frontend sera spécifié et reconstruit séparément à partir de la
maquette approuvée et des contrats backend existants. Les documents historiques
restent disponibles dans `docs/` et dans le journal de développement Notion.
