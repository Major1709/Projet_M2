# Résumé du projet

> Mis à jour le 9 septembre 2026. Ce document décrit l'état **exécutable** du projet.
> Le bilan historique du Sprint 0, qui décrivait une interface de démonstration
> alimentée par des données fictives, est remplacé : cette version-là n'existe plus.

## Objectif

NEXIA est un assistant web qui rassemble les connaissances de Jira, Confluence et
Figma. Il répond à des questions en citant ses sources, et il peut proposer des
modifications. **Une modification n'est jamais exécutée sans validation humaine.**

## Ce qui fonctionne aujourd'hui

### Lecture

L'assistant lit Jira, Confluence et Figma à travers des connecteurs fermés par défaut.
Une lecture n'aboutit que si elle traverse une liste blanche d'outils, une validation
de schéma, un contrôle d'empreinte du schéma distant, une liaison serveur des
identifiants sensibles, puis un audit. **16 outils de lecture** sont déclarés.

Il garde le fil de la conversation : « que dit KAN-2 ? » puis « et son statut ? »
fonctionne sans répéter la référence.

Pour Figma, un annuaire de cadres permet de demander « que contient le frame LOGIN ? »
sans coller de lien.

### Écriture, sous approbation

**5 outils d'écriture** sont déclarés : créer un ticket, commenter un ticket, changer
son statut, créer une page Confluence, mettre à jour une page.

Le parcours est toujours le même. Le modèle **propose**, la boucle s'arrête, un humain
**approuve** dans l'interface, puis le backend **exécute**. Entre l'approbation et
l'écriture, la cible est relue pour confirmer qu'elle n'a pas bougé, et le schéma de
l'outil est revérifié.

Ce qui est proposé au modèle est délibérément plus étroit que ce que les serveurs
acceptent : un champ qui permettrait d'écrire ailleurs que ce que l'écran annonce est
écarté, et chaque exclusion est justifiée dans `backend/app/mcp/mutation_registry.py`.

### Identité et traçabilité

L'identité vient d'une connexion Atlassian réelle (OAuth avec PKCE). Chaque lecture,
chaque proposition et chaque écriture laisse une trace en base, avec le locataire,
l'utilisateur et la corrélation. Une panne d'audit bloque l'action au lieu de la
laisser passer sans trace.

### Modèle de langage

Gemini `gemini-3.5-flash-lite`, à travers sa surface compatible OpenAI. L'adaptateur
Groq reste en place et fonctionnel : le retour arrière est l'échange de deux booléens.

## Ce qui n'est pas fait

- **La recherche sémantique est inactive.** Le module, la table vectorielle et le
  modèle sont choisis, mais rien n'est indexé et l'image est construite sans le moteur
  d'inférence. Le lien Jira↔Figma par le sens n'existe donc pas.
- **La découverte Figma est impossible** avec un jeton personnel : la portée
  `projects:read` n'est pas offerte. Les maquettes indexées sont désignées en
  configuration.
- **Aucune écriture Figma.** Le connecteur passe par l'API REST, pas par un serveur
  MCP, et une maquette se modifie dans l'outil de conception.
- Le service `worker` de Docker Compose n'est pas fonctionnel.

## Organisation du projet

| Dossier | Contenu |
|---|---|
| `frontend/` | Interface Next.js, chat et écran d'approbation |
| `backend/` | API FastAPI, connecteurs MCP, domaine d'approbation, agent |
| `infra/` | Docker Compose et surcouches par connecteur |
| `docs/` | Spécifications, architecture, sécurité, journaux de développement |

## Démarrage local

### Backend et services

Prérequis : Docker, et les secrets décrits dans [`../infra/README.md`](../infra/README.md).

```powershell
docker compose -f infra/compose.yaml `
  -f infra/compose.atlassian.yaml `
  -f infra/compose.atlassian-bindings.yaml `
  -f infra/compose.atlassian-oauth.yaml `
  -f infra/compose.auth-atlassian.yaml `
  -f infra/compose.figma.yaml `
  up -d
```

Les surcouches ne sont pas optionnelles : sans elles, les connecteurs restent éteints.
L'API répond sur `http://localhost:8000`, sa documentation sur `/docs`.

### Frontend

Prérequis : Node.js 20 ou plus récent.

```powershell
cd frontend
npm install
npm run dev
```

Ouvrir `http://localhost:3000` et se connecter à Atlassian.

## Vérifications

Au 9 septembre 2026, sur le commit `3f3cb5a` :

- **650 tests backend** hors intégration, **7 tests d'intégration** contre pgvector réel ;
- Ruff sans avertissement ;
- les 7 migrations appliquées sur une base vierge ;
- CI GitHub verte sur Python 3.11 et 3.12.

```powershell
cd backend
.venv\Scripts\python -m pytest -m "not integration"
.venv\Scripts\ruff check app tests
```

## État du projet

Le backend est complet pour le périmètre annoncé : lecture des trois sources, écriture
Jira et Confluence sous approbation humaine, audit, et intégration continue. La chaîne
a été éprouvée contre les serveurs réels — des tickets ont été créés depuis des phrases
en français, avec leur trace.

Ce qui reste relève de l'enrichissement, non du socle : la recherche sémantique, la
découverte Figma, et les écritures Confluence plus fines.

Pour plus de détails :

- [`development-logs/MCP-RW-001.md`](development-logs/MCP-RW-001.md) — l'écriture sous approbation ;
- [`development-logs/MCP-RO-ARCH-001.md`](development-logs/MCP-RO-ARCH-001.md) — les connecteurs en lecture ;
- [`product/mvp-spec.md`](product/mvp-spec.md) — les besoins fonctionnels ;
- [`architecture/system-architecture.md`](architecture/system-architecture.md) — l'architecture ;
- [`security/backend-security-review.md`](security/backend-security-review.md) — la sécurité.
