# Project Knowledge Assistant

Assistant IA web pour exploiter les connaissances Jira, Confluence et Figma, avec Groq comme fournisseur LLM, recherche RAG hybride et approbation humaine obligatoire avant toute mutation.

Le contexte métier durable se trouve dans [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md). L'organisation technique et les règles de dépendance sont décrites dans [docs/architecture/code-organization.md](docs/architecture/code-organization.md).

Pour une présentation simple de ce qui a été réalisé, voir [docs/resume-du-projet.md](docs/resume-du-projet.md).

## Applications

- `frontend/` : interface Next.js et module fonctionnel du chat projet ;
- `backend/` : monolithe modulaire FastAPI et contrats des intégrations ;
- `infra/` : contrat Docker Compose du MVP ;
- `docs/` : produit, architecture, sécurité et stratégie QA.

## Démarrage local

Frontend :

```powershell
cd frontend
npm install
npm run dev
```

Backend :

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m uvicorn app.main:app --reload
```

## Vérifications

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

Les adaptateurs Jira, Confluence, Figma, Groq et PostgreSQL ne sont pas encore implémentés. Le mode actuel utilise des données de démonstration côté frontend et des repositories en mémoire côté backend.
