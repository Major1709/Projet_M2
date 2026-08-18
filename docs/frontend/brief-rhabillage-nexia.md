# Brief de passation — rhabillage NEXIA

Destiné à la personne ou à l'agent qui reprend le chantier frontend pendant que le backend
avance en parallèle. Base de départ : `main` après le renommage NEXIA.

Ce document n'est pas une liste de souhaits. Les contraintes qu'il pose viennent de décisions
déjà prises et vérifiées en conditions réelles ; les défaire coûterait plus cher que le
chantier lui-même.

---

## 1. Ce que fait déjà l'application

Le 18 août 2026, le parcours complet a été prouvé depuis un navigateur, `correlation_id`
`327bda05-88de-49db-b2f6-5d7edf87bd73` : question posée dans l'interface, appel au modèle,
lecture Jira réelle, synthèse, citation cliquable vers le vrai ticket. Six événements d'audit
cohérents, aucune troncature.

**Ce chantier ne doit rien changer à ce comportement.** Il change l'apparence, rien d'autre.

---

## 2. Frontière de responsabilité

| Zone | Propriétaire pendant le chantier |
|---|---|
| `frontend/src/features/*/ui/**` | **Front** |
| `frontend/src/app/globals.css` | **Front, exclusivement** |
| `frontend/src/app/layout.tsx`, `page.tsx` | **Front** |
| `frontend/src/features/*/application/**` | Backend — ne pas modifier |
| `frontend/src/features/*/adapters/**` | Backend — ne pas modifier |
| `frontend/src/features/*/domain/models.ts` | **Contrat gelé** — ne pas modifier |
| `backend/**`, `infra/**`, `docs/development-logs/**` | Backend |

`globals.css` fait 1 695 lignes dans un seul fichier. C'est la source de conflit la plus
probable du chantier : pendant toute sa durée, le backend n'y touche pas, et le front est seul
à l'éditer.

---

## 3. Les trois interdits

### 3.1 Ne jamais remplir `confidence` ni `inferred`

`SourceReference` déclare ces deux champs, et la fixture de démonstration affiche
« IA · 86 % ». **Le backend ne les produit ni l'un ni l'autre**, et il ne le peut pas : ses
citations viennent de la provenance des lectures réellement effectuées, que rien ne score et
que rien n'infère.

Reprendre la maquette en câblant ce pourcentage est le réflexe naturel, puisque la maquette le
montre. Ce serait afficher une mesure que rien ne mesure. Les champs restent vides, et le
gabarit ne doit pas réserver de place pour eux dans le rendu des sources réelles.

Vérification : sur une réponse réelle, aucun pourcentage n'apparaît sous la citation. Sur la
fixture de démonstration, il apparaît. Ce contraste est voulu.

### 3.2 Supprimer deux libellés devenus faux

Ils étaient exacts tant que la passerelle était factice. Ils ne le sont plus :

- `ui/message-composer.tsx` — « Réponse simulée · aucune connexion MCP »
- `ui/assistant-workspace.tsx` — « Aucune donnée n'est envoyée à une source externe. »

La réponse est réelle, une lecture MCP a lieu, et la question part vers un fournisseur externe.
Les retirer, ou les conditionner à l'adaptateur réellement actif — l'information est disponible
dans `project-assistant-screen.tsx`, qui choisit entre démonstration et HTTP.

### 3.3 Ne pas construire pour les fixtures

`demo/fixtures.ts` contient des demandes `PORTAL-4xx` et une proposition d'action qui
ressemblent à de vraies données. Ce sont des décors. Le navigateur de demandes, la bande des
connecteurs et le panneau d'approbation ne sont **alimentés par aucun endpoint** aujourd'hui.

Conséquence pratique : ne pas déduire la forme des données réelles de ces objets. Seule la
conversation est vivante.

---

## 4. Contrat gelé

Le port, dans `application/assistant-gateway.ts` :

```ts
export interface ProjectAssistantGateway {
  indexRequests(requestIds: string[]): Promise<IndexationResult>;
  sendMessage(content: string): Promise<ChatMessage>;
  decideAction(proposal: ActionProposal, decision: ActionDecision): Promise<ActionDecisionResult>;
}
```

Une seule de ces trois méthodes atteint le backend. `indexRequests` n'a aucun index derrière
elle, `decideAction` déciderait sur des propositions que ce build ne produit pas : les deux
refusent explicitement plutôt que de simuler. **Ne pas les faire réussir pour rendre une
maquette plus démonstrative.**

`ChatMessage.status` vaut `"complete"`, `"streaming"` ou `"error"`. Le rendu doit distinguer les
trois : un refus affiché comme une réponse normale est un mensonge d'interface.

---

## 5. Périmètre du chantier

### Sans maquette supplémentaire — environ 2,25 jours

**R1 — Reprise sélective de la maquette.** Depuis `origin/feature/nexia-home-mockup` : les
quatre fichiers `frontend/src/features/nexia-home/**` et les 527 lignes ajoutées à
`globals.css`. L'ajout CSS est **purement additif** — 527 ajouts, zéro suppression — et toutes
les classes sont préfixées `nexia-`, donc aucune collision avec l'existant.

Ne **pas** reprendre : `.agents/skills/**` (~90 fichiers), `skills-lock.json`, `.codex-temp/`
(retiré et mis en `.gitignore` au titre du constat de revue S4), les binaires de `docs/`
(un `.docx` et trois captures). La branche supprime aussi 132 lignes de `package-lock.json` :
comprendre pourquoi avant de reprendre ce changement, ne jamais l'embarquer tel quel.

**R2 — Extraire les jetons.** La maquette code ses couleurs en dur — `#faf7f8`, `#fff`,
`#f1eeee`, `#111` — et ignore le système de jetons existant (`--ink-*`, `--mint-*`, `--paper`).
Extraire un jeu de jetons NEXIA **avant** de rhabiller quoi que ce soit, sinon chaque composant
recopiera des hexadécimaux et le thème deviendra impossible à faire évoluer.

**R3 — Coquille et routage.** Le rail devient le châssis de toute l'application, pas seulement
de l'accueil. Proposition : `/` sert l'accueil, `/assistant` sert l'espace de travail.

Deux choses à rendre vivantes au passage :

- Le composeur de l'accueil est aujourd'hui un `<textarea>` non contrôlé et un `type="button"`
  sans gestionnaire. Y écrire une question doit envoyer réellement.
- Les pastilles de connecteurs du rail sont figées en vert/vert/orange dans le JSX. Les brancher
  sur l'état réel, ou les retirer — une pastille verte qui ne mesure rien est un faux signal,
  exactement comme un score de confiance inventé.

**R6 — Nettoyage de nommage.** Le renommage Nexus → NEXIA est **déjà fait** (onze occurrences,
commit dédié). Restent les deux libellés du point 3.2.

### Bloqué faute de maquette — environ 2,5 jours

**R4 — Conversation** : messages, citations, états de chargement et d'erreur.
**R5 — Panneau d'approbation et navigateur de demandes.**

La maquette NEXIA **ne couvre que l'écran d'accueil** : rail, en-tête, trois cartes de capacité,
composeur. Elle ne définit ni fil de conversation, ni bulle de message, ni puce de citation, ni
panneau d'approbation, ni état d'erreur. Le commit intitulé `feat: creating chat Screen` ne
livre aucun écran de chat — ses modifications frontend se limitent à 26 lignes de CSS, 15 lignes
d'icônes et 8 lignes dans le composant d'accueil.

Deux voies, à trancher avant de commencer R4 :

1. **Les écrans existent dans Figma.** Les lire à la source. Le projet sait le faire :
   `getFigmaFile` et `getFigmaNode` sont vérifiés en conditions réelles. Il faut la clé du
   fichier — il n'y a pas encore de découverte automatique côté Figma.
2. **Ils n'existent pas.** Extrapoler à partir des jetons de l'accueil, et présenter le résultat
   comme une **proposition à valider**, jamais comme la maquette.

---

## 6. Vérification

À lancer depuis `frontend/` à chaque livraison, sans exception :

```bash
npm test
```

```bash
npx tsc --noEmit
```

```bash
npx eslint .
```

Attendu aujourd'hui : 21 tests verts, typecheck propre, **3 avertissements eslint** portant sur
`_requestIds`, `_proposal` et `_decision` — les paramètres volontairement inutilisés des deux
méthodes qui refusent. Ces trois-là préexistent ; tout avertissement supplémentaire vient du
chantier.

Aucun des 21 tests ne regarde le DOM : un rhabillage correct ne devrait en casser aucun. Si un
test tombe, c'est le signe qu'un fichier de `application/` ou `adapters/` a été modifié — donc
un franchissement de la frontière du point 2.

`next-env.d.ts` est régénéré par `next dev` et apparaît alors modifié. Le restaurer avant de
committer plutôt que de l'inclure.

### Vérifier de bout en bout

La démonstration complète demande le backend, avec sa pile — depuis `infra/` :

```bash
docker compose -f compose.yaml -f compose.atlassian.yaml -f compose.atlassian-oauth.yaml -f compose.atlassian-sites.yaml -f compose.atlassian-bindings.yaml -f compose.figma.yaml up -d api
```

et un `frontend/.env.local` portant les trois variables. **Si l'une des trois manque, l'écran
retombe silencieusement sur l'adaptateur de démonstration** et rien n'atteint le réseau — le
symptôme ressemble à une panne, ce n'en est pas une.

Le backend doit déclarer l'origine : `PKA_FRONTEND_ORIGINS=["http://localhost:3000"]`. Sans
elle, aucun middleware CORS n'est installé et le navigateur refuse la requête avant de
l'émettre.

Attention enfin au quota du fournisseur : le palier gratuit s'épuise vite et répond `429`. Ce
n'est pas un défaut de l'interface, et il ne faut ni relancer en boucle ni réduire le budget de
sortie pour compenser.

---

## 7. Mécanique de branches

Partir de `main`, une branche par tranche, et **ne jamais éditer `globals.css` depuis une
branche backend** pendant la durée du chantier. Le premier des deux chantiers à fusionner
impose au second de se rebaser : c'est le prix d'un fichier CSS unique, et il est plus faible
que celui d'un conflit résolu à l'aveugle.
