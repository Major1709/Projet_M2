# MCP-RW-001 — Écriture sous approbation humaine, et découverte de cadres Figma

## Exécution

- Déclencheur : ordre explicite dans le chat, en plusieurs tranches successives
- Taille : XL
- Branche : `feat/ecriture-jira` (le nom ne couvre plus le contenu, voir *Limites*)
- Commit fonctionnel : `3f3cb5a`, fusionné dans `main` par la PR #8 (`0e90bcf`)
- Tâches associées : `MCP-RW-001`, `AGENT-PROP-001`, `FIGMA-CAT-001`, `OBS-HEALTH-001`
- Statut : `Done` — cinq écritures qualifiées contre les serveurs réels,
  `KAN-33` et `KAN-34` créés depuis des phrases en français le 2026-09-07

## Objectif et résultat

L'assistant sait désormais **proposer** une écriture, un humain l'**approuve**, et le
backend l'**exécute** avec trace. Avant cette tranche, `ApprovedMutationRunner`
existait mais était écrit contre un `MCPToolGateway` que personne ne réalisait : la
chaîne était théorique de bout en bout.

Cinq outils d'écriture sont déclarés, trois côté Jira et deux côté Confluence. Une
écriture n'aboutit que si elle traverse, dans cet ordre : registre de mutations
séparé, validation du schéma public, injection serveur du liant, revalidation de
permission par une lecture réelle de la cible, réservation d'idempotence, contrôle de
dérive du schéma **juste avant l'appel**, puis exécution avec état `EXECUTING` commité
avant que le fournisseur soit contacté.

Points structurants :

- **Registre séparé** (`mutation_registry.py`) : `ToolContract` refuse tout contrat
  non-`READ`, et cette invariante est ce qui rend le chemin de lecture digne de
  confiance. L'assouplir aurait échangé une garantie structurelle contre un booléen.
  L'invariante est donc inversée dans le registre d'écriture, chacun gardant la sienne,
  vérifiée à la construction.
- **La surface déclarée est plus étroite que ce que le serveur accepte**, et ce sont
  les refus qui portent le sens. `additional_fields` est le seul moyen de fixer
  priorité, étiquettes et champs personnalisés chez Atlassian : une proposition qui le
  porterait afficherait « créer un ticket intitulé X » tout en pouvant écrire ailleurs.
  `commentId` transformerait un ajout de commentaire en réécriture d'un commentaire
  d'autrui. `fields` et `update` modifieraient n'importe quel champ *au passage* d'une
  transition. `spaceId` et `parentId` **déplaceraient** une page Confluence.
  `isPrivate` créerait une page invisible pour l'équipe.
- **Lever ou rendre un échec** gouverne toute la passerelle, parce que les deux ne
  disent pas la même chose à la réservation d'idempotence. Rendre un échec signifie
  « l'écriture n'a pas eu lieu, et je le sais » ; lever signifie « j'ignore où en est
  cette écriture », la réservation reste ouverte et la reprise honnête représente la
  **même** clé.
- **Le modèle propose, il ne décide pas.** La classe d'action et le système source
  viennent du contrat, jamais de ce que le modèle a renvoyé — sans quoi une suppression
  pourrait s'afficher comme une création dans l'écran d'approbation. Une écriture
  arrête la boucle immédiatement : chaque écriture doit être vue et approuvée
  séparément.
- **Une modification épingle la version** que l'humain a sous les yeux. L'agent lit
  donc la ressource au moment de proposer, par le chemin de lecture ordinaire. Sans
  cette lecture, la revalidation aurait refusé toute modification — une panne qui ne se
  serait vue qu'à la première exécution.
- **Le domaine exige un diff pour toute modification**, et une mise à jour Confluence
  remplace le corps entier : le diff montre donc les deux versions avec un drapeau
  `replaces_everything`. Une troncature au-delà de 4 000 caractères est annoncée, jamais
  silencieuse.
- **Annuaire de cadres Figma** : l'API ne sait pas chercher un cadre. L'annuaire
  indexe les maquettes désignées, se rafraîchit sur échec de recherche, et rend de quoi
  construire la vraie lecture. Il vit en mémoire — son contenu est entièrement dérivé
  de Figma, donc reconstructible.

## Rôles mobilisés

- Architecte / Tech Lead : séparation des registres, contrat de proposition, coordination
  du contrat HTTP avec le frontend
- MCP / Sécurité : surface d'écriture, refus par champ, épinglage de schéma, idempotence
- Backend : registre de mutations, passerelle, interception dans la boucle d'agent,
  annuaire Figma, sonde de disponibilité
- QA / Test Automation : campagne unitaire et essais réels contre Jira, Confluence et Figma

## Fichiers et modules principaux

- `backend/app/mcp/mutation_registry.py` : contrats d'écriture, schémas publics et fournisseur
- `backend/app/mcp/adapters/mutation_gateway.py` : transport d'une écriture approuvée
- `backend/app/approvals/adapters/tool_pin.py` : épinglage adossé au registre
- `backend/app/agent/read_workflow.py` : proposition, diff, annuaire, mémoire conversationnelle
- `backend/app/figma/catalogue.py` : annuaire de cadres
- `backend/app/core/database.py` : sonde de disponibilité adossée à la tête de migration
- `backend/app/core/logging.py` : rédaction des paramètres sensibles dans les journaux
- `backend/app/agent/adapters/openai_compatible.py`, `gemini.py`, `groq.py`
- `backend/tests/test_mutation_*.py`, `test_agent_proposes_writes.py`,
  `test_figma_catalogue.py`, `test_readiness_schema.py`, `test_log_redaction.py`
- `infra/compose.yaml`, `infra/.env.example`

## Vérifications et preuves

Campagne rejouée le 2026-09-09 sur le commit `3f3cb5a` :

- Pytest complet : `650 passed, 7 deselected`
- Pytest d'intégration contre pgvector réel : `7 passed`
- Ruff sur `app` et `tests` : `All checks passed!`
- Migrations sur base vierge : les 7 révisions jusqu'à `20260831_0007`
- CI GitHub verte sur Python 3.11 **et** 3.12 — la première exécution réussie du projet
- 16 lectures et 5 écritures déclarées, toutes empreintes conformes aux serveurs vivants

Essais réels :

| Essai | Résultat |
|---|---|
| `createJiraIssue` depuis une phrase en français | `KAN-34` créé, relu avec sa citation |
| `addCommentToJiraIssue` | commentaire posté, confirmé par l'utilisateur |
| Lecture Figma par URL collée | `getFigmaNode`, parcours START → LOGIN décrit |
| Annuaire de cadres | 3 entrées indexées, `nodeId` suivi après modification de la maquette |
| Sonde de disponibilité | `200` → schéma falsifié → `503` → restauré → `200` |

## Défauts trouvés, et par quoi

Six défauts, dont **quatre qu'aucun test unitaire ne pouvait attraper**. Ils sont
consignés ici parce qu'ils constituent l'argument le plus solide du projet sur la
valeur des essais bout-en-bout.

| Défaut | Comment il a été trouvé |
|---|---|
| Empreinte de dérive aveugle sur une propriété nommée `description` ou `title` | En lisant le schéma réel du serveur au lieu de le supposer |
| Refus du fournisseur rapporté comme « issue inconnue » | En créant un vrai ticket |
| Clé du ticket créé introuvable | Idem |
| Base de développement deux migrations en retard, service `healthy` | Première écriture réelle |
| Code d'autorisation OAuth en clair dans les journaux uvicorn | Lecture des journaux après une connexion |
| Catalogue offrant 4 outils Figma alors que le connecteur était éteint | Mesure du coût en tokens |

**La cause racine des deux défauts de passerelle est la même** : le double de test
portait un attribut `is_error` que `RemoteToolResult` n'a pas. La branche de refus
était du code mort, et quatorze tests la couvraient — ce qui la faisait passer pour
éprouvée. Le double a été corrigé pour ne rien offrir que l'original ne porte.

## Limites connues et blocages

- **La clé d'idempotence n'est pas transmise au fournisseur.** Le serveur MCP
  d'Atlassian n'expose aucun paramètre d'idempotence et son schéma est fermé. La
  protection est à sens unique : une même approbation n'est jamais dépensée deux fois,
  mais un appel interrompu laisse une issue que seul le fournisseur pourrait trancher.
- **Le statut d'arrivée d'une transition n'est pas résolu en nom.** Le diff porte
  `to_transition_id`. Annoncer « vers Terminé » sans l'avoir vérifié mentirait à
  l'humain au moment où il décide.
- **La découverte Figma est impossible avec un jeton personnel.** Sondé en direct le
  2026-09-09 : `/v1/teams/{id}/projects` exige la portée `projects:read`, absente de la
  liste offerte aux jetons personnels. Les portées accordées sont `current_user:read`,
  `file_content:read`, `file_metadata:read` et `folders:read`, et aucun listing global
  n'existe (`/v1/files`, `/v1/me/files`, `/v1/projects` répondent 404). Un flux OAuth
  Figma lèverait la limite ; il a été écarté au regard du bénéfice.
- **L'annuaire de cadres est en mémoire.** Un redémarrage le vide et la première
  question suivante paie une relecture.
- **`mutations.execute()` est synchrone** et ne peut pas être appelé depuis une boucle
  d'événements. La route étant un `def` ordinaire, FastAPI l'exécute dans un fil et le
  chemin de production fonctionne — mais passer la route en `async def` casserait à
  l'exécution, pas à la compilation.
- **Le nom de branche `feat/ecriture-jira` ne couvre plus son contenu** : Confluence,
  Figma, l'interface d'approbation et la sonde de disponibilité y figurent aussi.
- **L'index sémantique reste inactif** : `embeddings_enabled = False`, aucun vecteur en
  base, et l'indexeur ne couvre que Jira. Le lien Jira↔Figma par le sens n'est donc pas
  réalisé, mais l'annuaire produit exactement les documents qu'il consommerait.

## Suite

- Persister l'annuaire de cadres, ou l'alimenter depuis l'index sémantique
- Résoudre le nom du statut d'arrivée d'une transition, via `getTransitionsForJiraIssue`
- Rendre explicite la précondition synchrone de `execute_mutation`
- Renommer la branche avant qu'elle serve de référence historique
- Activer les embeddings et écrire un indexeur Figma, si le coût de construction le permet
