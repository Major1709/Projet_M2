# Jeu d'évaluation du rapprochement sémantique

Corpus synthétique destiné au projet Jira `KAN`, et deux jeux de référence permettant de mesurer
la recherche et le rapprochement de la phase 3. Aucun de ces fichiers ne crée quoi que ce soit :
l'import dans Jira est une action manuelle et délibérée.

## Ce que ce jeu vaut, et ce qu'il ne vaut pas

Il **valide le fonctionnement technique** : que l'indexation conserve la provenance, que la
recherche hybride place les bons tickets en tête, que le rapprochement distingue une reformulation
d'un simple partage de vocabulaire, et que le filtre de droits s'applique avant l'exposition au
modèle.

Il **ne mesure pas les performances sur un vrai corpus bancaire**. Les textes ont été écrits pour
que les relations attendues soient connues, ce qui est exactement ce qu'un corpus réel n'offre pas :
formulations bâclées, doublons partiels, tickets sans description, vocabulaire interne, mélange de
langues. Un score obtenu ici est une condition nécessaire, jamais une preuve de qualité en
production. **Aucun seuil de similarité ne doit être figé sur ces seules données.**

Toutes les données sont inventées. Aucun nom, numéro de compte, coordonnée ni élément réel
d'AccèsBanque n'y figure.

## Composition du corpus

30 tickets, `SEED-01` à `SEED-30`, sur des sujets de canaux bancaires, parcours client, paiements,
authentification, crédit, cartes et notifications.

| Catégorie | Effectif | Rôle dans la mesure |
|---|---|---|
| Paires décrivant le même besoin | 7 paires (`SEED-01` à `SEED-14`) | Le vocabulaire diffère volontairement d'un membre à l'autre. Un moteur purement lexical doit échouer à les rapprocher. |
| Faux amis | 6 paires | Partagent un mot saillant — carte, virement, code, solde, crédit, notification — pour des problèmes distincts. Ils sanctionnent la correspondance de termes. |
| Rapprochements légitimes non-doublons | 4 paires | Même famille de défaut, besoin différent. Ils vérifient qu'on ne collapse pas `related` sur `duplicate`. |
| Contrôles sans relation | 5 paires | Plancher de bruit. |

Les identifiants de paire n'apparaissent **nulle part** dans les résumés, les descriptions ou les
étiquettes, et aucun texte ne contient d'indication du type « doublon ». Les descriptions font
plusieurs phrases pour que la similarité porte sur le sens et non sur le seul titre.

## Les fichiers

### `jira_seed_tickets.csv`

Colonnes : `Id`, `Issue Type`, `Summary`, `Description`, `Priority`, `Labels 1`, `Labels 2`.
Uniquement des champs Jira standards. `Id` est un identifiant temporaire propre à ce jeu : Jira
attribuera ses propres clés `KAN-n` à l'import, et c'est la correspondance entre les deux qu'il
faut conserver.

### `semantic_pairs_gold.csv`

Colonnes : `ticket_a`, `ticket_b`, `relation`, `justification`.
`relation` vaut `duplicate`, `related` ou `unrelated`. 22 paires.

Les paires absentes du fichier ne sont **pas** implicitement `unrelated` : elles sont simplement
non jugées. Compter un couple non listé comme un négatif fausserait la précision.

### `retrieval_queries_gold.csv`

Colonnes : `query_id`, `query`, `expected_ticket_ids`, `piege_attendu`, `note`.
14 requêtes écrites comme un client les formulerait, sans reprendre les mots des résumés.
`expected_ticket_ids` liste les tickets attendus dans les premiers résultats, séparés par `;`.

`piege_attendu` est la colonne qui donne sa valeur au jeu : elle nomme les tickets qui partagent du
vocabulaire avec la requête **sans y répondre**. Une recherche qui les classe devant les tickets
attendus fait de la correspondance de mots, pas de la recherche sémantique.

## Importer dans Jira

1. Projet `KAN`, puis **Paramètres du projet → Importer des données externes → CSV**.
2. Charger `jira_seed_tickets.csv`. Le fichier est en **UTF-8** ; le sélectionner explicitement si
   l'assistant propose un autre encodage, sans quoi les accents seront corrompus.
3. Mapper les colonnes : `Summary` → Résumé, `Description` → Description, `Issue Type` → Type de
   ticket, `Priority` → Priorité. Mapper **`Labels 1` et `Labels 2` toutes deux vers Étiquettes** —
   l'assistant accepte plusieurs colonnes vers un champ multivalué.
4. Ne pas mapper `Id`. Le conserver hors de Jira, dans un tableau de correspondance
   `SEED-nn → KAN-nn`, que les deux jeux de référence exigent pour être exploitables.
5. L'écran suivant demande la correspondance des valeurs. Les priorités sont écrites `High`,
   `Medium`, `Low` : les rattacher aux priorités de l'instance, dont les libellés sont en français.
   Même chose pour `Bug` et `Task` si les types du projet portent d'autres noms.

L'import crée 30 tickets réels. Ils sont indiscernables de vrais tickets une fois créés : leur
seule marque distinctive est la table de correspondance conservée à l'étape 4. Prévoir une
étiquette supplémentaire ou un libellé de version si le projet doit rester nettoyable.

## Mesurer

Sur `retrieval_queries_gold.csv`, les indicateurs utiles sont le rappel dans les premiers résultats
et la position du premier ticket attendu. Suivre séparément le **taux de pièges classés devant un
ticket attendu** : c'est lui qui distingue une recherche sémantique d'une recherche lexicale, et
c'est la seule mesure qui bouge vraiment quand on ajoute les vecteurs.

Sur `semantic_pairs_gold.csv`, ne pas se contenter d'un taux global. Un système qui déclare tout
`unrelated` obtient déjà une bonne exactitude, puisque `unrelated` est la classe majoritaire. Les
7 paires `duplicate` et les 6 faux amis sont les seules qui portent de l'information.

Enfin, un test de fuite ne s'improvise pas ici : il demande deux identités aux droits différents et
une vérification que ni le ticket, ni son titre, **ni la justification du rapprochement** ne
laissent transparaître un contenu inaccessible.
