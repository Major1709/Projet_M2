# Frontend — Nexus Project Intelligence

Shell UX autonome du chat projet. Il illustre le parcours Jira → RAG → analyse sourcée → proposition Confluence → approbation humaine.

## Démarrer localement

Pré-requis : Node.js 20+ et npm.

```bash
npm install
npm run dev
```

Puis ouvrir `http://localhost:3000`.

Vérifications prévues :

```bash
npm run typecheck
npm run lint
npm run test
npm run build
```

## Ce que contient le shell

- Next.js App Router, React et TypeScript strict ;
- liste responsive de demandes Jira sélectionnables ;
- déclenchement explicite d’une indexation locale simulée ;
- conversation avec références Jira, Confluence et Figma ;
- indication explicite des relations inférées par l’IA ;
- aperçu d’une modification Confluence : cible, champs, diff, sources, version et hash ;
- boutons approuver, modifier et rejeter ;
- états d’approbation visibles et non dépendants de la seule couleur ;
- interactions au clavier, focus visibles, zones annoncées avec `aria-live` et réduction des animations selon la préférence système ;
- adaptation bureau, tablette et mobile sans bibliothèque CSS externe.

## Organisation

```text
src/app/                                      routes Next.js et styles globaux
src/features/project-assistant/domain/        contrats métier
src/features/project-assistant/application/   état, cas d'usage et port du gateway
src/features/project-assistant/adapters/      adaptateurs externes ou locaux
src/features/project-assistant/ui/            composants de présentation
src/features/project-assistant/demo/          composition et fixtures de démonstration
```

`useAssistantWorkspace` porte les transitions de l'écran derrière cinq actions utilisateur. Les composants restent contrôlés et sans connaissance du transport. `ProjectAssistantGateway` constitue la frontière à implémenter par le futur client HTTP/SSE.

## Contrats backend attendus

Le frontend est aligné sur les routes indicatives de l’architecture, mais aucune route réseau n’est encore appelée :

```text
POST /api/conversations/{id}/messages
GET  /api/conversations/{id}/events              # SSE
POST /api/ingestions/jira-selection
GET  /api/ingestions/{id}
GET  /api/actions/{id}
POST /api/actions/{id}/approve
POST /api/actions/{id}/reject
POST /api/actions/{id}/revise
```

Les réponses devront notamment fournir :

- des messages avec sources déjà filtrées selon les droits courants ;
- un identifiant, une URL/référence, une version et une provenance par source ;
- un `ActionProposal` versionné avec cible exacte, payload affichable, diff, hash, expiration et identifiant de corrélation ;
- une version attendue et un jeton anti-rejeu pour chaque décision ;
- les états d’indexation et d’exécution asynchrones ;
- les résultats partiels détaillés et les erreurs sûres, sans secret.

Le frontend ne doit jamais être la frontière d’autorisation. Le backend doit recontrôler les permissions juste avant toute mutation et invalider l’approbation si le payload, la cible ou le contexte a changé.

## Limites actuelles

- Toutes les données sont fictives et définies dans `src/features/project-assistant/demo/fixtures.ts`.
- Le service de démonstration utilise seulement des délais locaux ; il n’appelle ni Groq, ni MCP, ni API.
- L’authentification, la recherche, les liens sources, le streaming SSE et la persistance ne sont pas implémentés.
- Les boutons de navigation hors Assistant sont désactivés.
- La décision « Modifier » place la proposition courante dans l'état `SUPERSEDED` ; un futur éditeur devra produire une nouvelle proposition et une nouvelle version à approuver.
- L’approbation s’arrête volontairement à `PERMISSION_CHECK` en démonstration : aucune réussite MCP fictive n’est affichée.
- La politique de suppression renforcée, la granularité d’approbation des lots et l’auto-approbation restent des décisions produit ouvertes.
