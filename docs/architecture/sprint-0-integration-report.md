# Rapport d'intégration — Sprint 0

Date : 2026-08-04

## Résultat

Les huit rôles du projet ont été activés et ont livré un premier socle cohérent. Le dépôt contient maintenant les contrats produit, l'architecture, la conception RAG/graphe, la politique MCP/sécurité, un scaffold frontend, un scaffold backend, une infrastructure de développement et une stratégie QA.

Le résultat est adapté à un Sprint 0 et à la préparation d'un premier parcours vertical en lecture. Il est volontairement **NO-GO pour toute mutation MCP réelle** tant que les contrôles bloquants de sécurité et de persistance ne sont pas implémentés.

## Équipe et livrables

| Rôle | Livrable principal |
|---|---|
| Architecte / Tech Lead | `docs/architecture/system-architecture.md` et coordination |
| Product / Business Analyst | `docs/product/mvp-spec.md` |
| Frontend / UX | `frontend/` |
| Backend | `backend/` |
| IA / RAG / Knowledge Graph | `docs/architecture/knowledge-rag-design.md` |
| MCP / IAM / Sécurité | `docs/security/mcp-security-design.md` et revue backend |
| QA / Test Automation | `docs/qa/test-strategy.md` |
| DevOps / SRE | `infra/` |

Le mode de collaboration et la propriété des fichiers sont décrits dans `docs/architecture/agent-operating-model.md`.

## Contenu livré

### Produit

- 17 cas d'usage.
- 14 User Stories priorisées avec critères d'acceptation.
- Parcours Jira vers RAG, Confluence puis backlog Jira.
- Gouvernance des approbations et questions fonctionnelles ouvertes.

### Architecture et IA

- Monolithe modulaire FastAPI pour le MVP.
- Next.js pour le chat et les écrans d'approbation.
- Groq derrière une interface fournisseur.
- PostgreSQL et pgvector au MVP.
- Recherche lexicale et vectorielle, fusion RRF puis reranking.
- Graphe métier déterministe dans PostgreSQL avant décision éventuelle d'introduire Neo4j.
- Provenance, citations et filtrage d'accès prévus comme invariants.

### Frontend

- Shell Next.js App Router et TypeScript strict.
- Liste de demandes Jira et indexation simulées.
- Chat avec références de sources.
- Panneau de proposition avec cible, contenu et diff.
- Actions d'approbation, modification et rejet simulées.
- Aucun appel réseau ou MCP réel.

### Backend

- App factory FastAPI et endpoint `/health`.
- Conversations et propositions d'action en mémoire pour le développement.
- Transitions approve, reject et revise avec version optimiste.
- Snapshot canonique et hash de proposition.
- Contrats abstraits LLM, MCP, permissions source, RAG et audit.
- Garde interdisant l'exécution MCP avant l'état `APPROVED`.
- Six tests unitaires centrés sur l'approbation et la garde MCP.

### DevOps et QA

- Compose pour frontend, API, worker, PostgreSQL/pgvector et Redis.
- Réseaux séparés, healthchecks, volumes, secrets par fichiers et profils d'exploitation.
- Stratégie QA couvrant permissions, multi-tenant, approbation, TOCTOU, idempotence, prompt injection, RAG, contrats MCP, E2E, performance et résilience.

## Vérifications effectuées

| Vérification | Résultat |
|---|---|
| Syntaxe Python par analyse AST | OK, 32 fichiers |
| Lecture et parsing de `frontend/package.json` | OK |
| `docker compose ... config --quiet` | OK |
| Artefacts `__pycache__` | Nettoyés |
| Tests pytest | Non exécutés : dépendances absentes |
| Build/typecheck frontend | Non exécuté : dépendances absentes |
| Build des images | Non exécuté : Dockerfiles encore absents |
| Tests MCP/RAG réels | Non exécutables : intégrations non implémentées |

L'avertissement Docker local relatif à l'accès à `~/.docker/config.json` n'a pas empêché la validation du fichier Compose.

## Verdict sécurité

Les abstractions sont fail-closed et aucun connecteur réel n'est actif. Cela limite le risque immédiat, mais ne constitue pas une autorisation de brancher des outils de mutation.

Blocants avant toute mutation MCP :

1. Lier de façon déterministe la cible affichée, le payload approuvé et les arguments réellement exécutés.
2. Remplacer les identités fournies par en-têtes par OIDC et une identité MCP/source déléguée vérifiable.
3. Implémenter un registre d'outils et une allowlist `default deny` avec schémas fermés.
4. Ajouter expiration, liaison de session et version d'outil aux approbations ; ne pas exposer ni stocker en clair le secret anti-rejeu.
5. Revalider permissions, version et ETag/hash de la ressource juste avant la mutation.
6. Générer et réserver les clés d'idempotence côté serveur dans un stockage durable.
7. Rendre l'audit durable et atomique avec la mutation ou une outbox transactionnelle.
8. Implémenter le broker OAuth et les défenses déterministes contre les instructions malveillantes provenant des sources.

Le détail est disponible dans `docs/security/backend-security-review.md`.

## Écarts d'intégration

- Les types frontend et backend des propositions d'action ne sont pas encore identiques.
- Certains noms d'états divergent et l'expiration manque dans le backend.
- Le frontend n'expose pas encore le jeton ou la version attendue par le contrat backend.
- Le backend utilise des repositories mémoire et des identités de développement.
- Le Compose attend des Dockerfiles, `/api/health`, `/health/ready`, Celery et Alembic qui ne sont pas encore implémentés.
- Les variables Compose ne sont pas encore alignées avec le préfixe de configuration backend.
- Aucun pipeline CI n'existe encore.

## Sprint 1 recommandé

Ordre de réalisation proposé :

1. **Architecte + Frontend + Backend** : définir un contrat OpenAPI unique pour conversation, source, proposition et décision, puis générer ou aligner les types TypeScript.
2. **MCP/Sécurité + Backend** : implémenter OIDC, contexte d'identité serveur et registre MCP `default deny`, sans activer les mutations.
3. **Backend + DevOps** : ajouter PostgreSQL, migrations Alembic, audit durable, outbox et idempotence côté serveur.
4. **Backend + IA/RAG** : implémenter le premier parcours lecture seule Jira MCP vers ingestion, recherche autorisée et réponse Groq avec citations.
5. **Frontend** : remplacer les fixtures par le contrat BFF et ajouter les états d'erreur/chargement réels.
6. **DevOps** : ajouter Dockerfiles, endpoints de readiness, worker réel et pipeline CI.
7. **QA** : automatiser les tests de contrat, d'isolation tenant, d'approbation et le premier E2E lecture seule.
8. **Sécurité** : refaire un go/no-go avant d'activer une première création Confluence.

## Conditions de fin du Sprint 1

- Un utilisateur authentifié ne peut récupérer que ses demandes Jira autorisées.
- Une demande sélectionnée peut être indexée avec provenance et périmètre d'accès.
- Le chat répond avec au moins une citation Jira vérifiable.
- Les recherches inter-tenant et les accès IDOR échouent systématiquement.
- Les contrats frontend/backend et les images de développement sont validés en CI.
- Tous les outils MCP de mutation restent désactivés.

