# Organisation maintenable du code

## Objectif

Le dépôt est organisé par capacité métier, puis par responsabilité interne. Une fonctionnalité doit pouvoir évoluer sans obliger le reste de l'application à connaître son framework, son SDK distant ou ses règles d'état.

La règle principale est la suivante : le domaine et les workflows dépendent de contrats stables ; les détails réseau, base de données et interface graphique dépendent de ces contrats.

## Frontend

```text
frontend/src/
  app/                                  composition Next.js et styles globaux
  features/
    project-assistant/
      domain/                           types et vocabulaire métier
      application/                      état, cas d'usage et port du gateway
      adapters/                         implémentations HTTP/SSE ou démonstration
      ui/                               composants de présentation
      demo/                             fixtures et composition de démonstration
      index.ts                          interface publique de la feature
```

Conventions :

- `src/app` compose les features, sans contenir leurs règles métier ;
- `domain` n'importe ni React, ni Next.js, ni client HTTP ;
- `application` expose un petit nombre d'actions utilisateur et dépend du port `ProjectAssistantGateway` ;
- `adapters` traduit un protocole externe vers ce port ;
- `ui` reçoit l'état et les actions du module applicatif ;
- les autres features importent uniquement le fichier public `index.ts` ;
- les tests de règles d'état restent près du module testé avec le suffixe `.test.ts` ou `.test.tsx`.

Le futur client backend remplacera `demo-assistant-gateway.ts` par un adaptateur HTTP/SSE sans modifier les composants ni les règles d'état.

## Backend

```text
backend/app/
  main.py                               création de l'application HTTP
  bootstrap.py                          composition des implémentations
  core/                                 configuration et identité transversales
  approvals/
  conversations/
  audit/
  knowledge/
  mcp/
  agent/
    domain.py                           valeurs et contrats métier
    errors.py                           erreurs du domaine, si nécessaire
    ports.py                            interfaces requises par le domaine
    workflow.py                         cas d'usage et transitions
    api.py                              adaptateur entrant FastAPI
    adapters/                           adaptateurs sortants concrets
    __init__.py                          interface publique du module
```

Tous les domaines n'ont pas besoin de chaque fichier. On ajoute une séparation seulement lorsqu'une responsabilité réelle existe.

Conventions de dépendance :

```text
api -> workflow -> domain
                  -> ports <- adapters
bootstrap -> workflows + adapters
```

- `domain.py` ne dépend pas de FastAPI, d'un SDK MCP ou d'une base de données ;
- `workflow.py` porte les autorisations applicatives et transitions métier ;
- `ports.py` décrit les capacités externes requises, sans imposer de technologie ;
- `api.py` traduit HTTP vers le workflow et les erreurs métier vers des statuts HTTP ;
- `adapters/` contient les implémentations PostgreSQL, MCP, Groq ou mémoire ;
- `bootstrap.py` est l'unique racine de composition des implémentations ;
- `__init__.py` expose l'interface publique stable du module ;
- les tests métier passent par cette interface ou par l'API, sans dépendre des détails internes sauf pour tester explicitement un adaptateur.

## Ajout d'une intégration

Pour Jira, Confluence, Figma, Groq ou le stockage RAG :

1. définir ou compléter le port dans le domaine propriétaire ;
2. écrire les tests du workflow contre un faux ou un adaptateur mémoire ;
3. implémenter l'adaptateur concret dans `adapters/` ;
4. le câbler dans `bootstrap.py` ;
5. exposer seulement les types nécessaires dans `__init__.py` ;
6. documenter les variables de configuration et les erreurs observables.

Un SDK externe ne doit pas traverser la frontière de son adaptateur. Les objets Atlassian, Figma ou Groq sont traduits vers les modèles internes dès leur entrée.

## Garde-fous

- Toute création, modification ou suppression externe passe par `ApprovalWorkflow`, puis par `ApprovedMutationRunner` après approbation.
- L'interface utilisateur ne constitue jamais une frontière d'autorisation.
- Le RAG reste un index dérivé ; ses modèles ne remplacent pas les identifiants, versions et permissions des sources.
- Les relations inférées par l'IA conservent provenance et confiance, séparées des relations déterministes.
- Un nouveau dossier générique `utils`, `services` ou `common` n'est créé que si son propriétaire et son contrat sont explicites.
