# Mode de collaboration des 8 agents

## Équipe

1. Architecte / Tech Lead — agent principal et intégrateur.
2. Product / Business Analyst.
3. Frontend / UX.
4. Backend.
5. IA / RAG / Knowledge Graph.
6. MCP / IAM / Sécurité.
7. QA / Test Automation.
8. DevOps / SRE.

## Règle de parallélisme

L'environnement permet quatre exécutions simultanées, agent principal inclus. Les huit rôles travaillent donc en vagues coordonnées avec au plus trois spécialistes parallèles et l'architecte.

```text
Vague 1 : Architecte + Product + IA/RAG + MCP/Sécurité
Vague 2 : Architecte + Frontend + Backend + DevOps
Vague 3 : Architecte + QA + corrections ciblées des spécialistes
```

Les rôles sont stables même lorsqu'ils ne sont pas actifs simultanément. Un agent peut recevoir une nouvelle tâche de son domaine lors d'une vague suivante.

## Propriété des fichiers

- Architecte : `docs/architecture/system-*`, décisions et intégration transversale.
- Product : `docs/product/`.
- Frontend : `frontend/`.
- Backend : `backend/`, sauf modules explicitement délégués.
- IA/RAG : conception IA et, après contrat, `backend/app/knowledge/`.
- MCP/Sécurité : `docs/security/` puis `backend/app/mcp/` et contrôles d'autorisation convenus.
- QA : `docs/qa/`, tests E2E et tests transversaux.
- DevOps : `infra/`, fichiers de conteneurisation et pipelines CI.

Deux agents ne modifient pas simultanément le même fichier. Toute modification hors du périmètre attribué est annoncée à l'architecte avant édition.

## Contrats de collaboration

### Product vers développement

Chaque fonctionnalité fournit : acteur, préconditions, scénario nominal, erreurs attendues, permissions, exigences d'approbation et critères d'acceptation.

### Architecture vers frontend/backend

Chaque parcours transverse fournit : états, contrats de requête/réponse, événements, erreurs et invariants de sécurité.

### Backend vers IA/MCP

Le backend définit des interfaces de domaine indépendantes des SDK : `LLMProvider`, `MCPToolGateway`, `KnowledgeRetriever`, `ApprovalRepository` et `AuditSink`.

### Développement vers QA

Chaque fonctionnalité expose : critères d'acceptation, commandes de test, données de test, erreurs connues et points d'observabilité.

## Definition of Done commune

Une tâche n'est terminée que si :

- le comportement correspond aux critères d'acceptation ;
- les permissions et l'approbation sont traitées explicitement ;
- les entrées et sorties sont validées ;
- les erreurs sont observables sans exposer de secret ;
- les tests pertinents existent et passent ;
- la documentation ou le contrat associé est à jour ;
- aucun autre domaine n'est modifié implicitement.

## Règles de décision

- L'agent Product décide du sens fonctionnel, avec validation finale du porteur du projet.
- L'agent Sécurité peut bloquer une mutation ou un flux qui contourne l'approbation ou les permissions.
- L'agent QA peut refuser la clôture d'une fonctionnalité dont les critères ne sont pas vérifiables.
- L'architecte tranche les conflits de frontières techniques et assure l'intégration.
- Une hypothèse non confirmée est documentée comme telle et ne devient pas silencieusement une exigence.

## Premier incrément vertical

Le premier incrément doit couvrir un parcours complet et limité :

```text
Connexion utilisateur
  -> liste de demandes Jira autorisées
  -> sélection d'une demande
  -> indexation
  -> question dans le chat
  -> réponse Groq avec citation Jira
  -> aucune mutation
```

Le deuxième incrément ajoute une mutation Confluence avec proposition persistée, aperçu, approbation et audit. La copie vers Jira et les écritures Figma viennent ensuite.
