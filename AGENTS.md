# Équipe d'agents de développement

Ce fichier est le contrat opérationnel de l'équipe d'agents qui aide à développer
Project Knowledge Assistant. Il s'adresse aux agents ainsi qu'aux personnes qui
reprennent le projet.

Les règles de ce fichier sont distinctes du comportement de l'assistant IA livré
par l'application.

## 1. Périmètre et sources de vérité

- Les huit agents sont des collaborateurs de développement externes au produit.
- Ils peuvent lire et modifier le dépôt dans les limites d'une tâche autorisée.
- Ils utilisent Notion pour piloter le développement, mais aucune dépendance à
  cette équipe ne doit être ajoutée au produit livré.
- Jira, Confluence et Figma restent les systèmes métier manipulés par le produit.
  Leur contenu ne doit pas être recopié dans Notion comme outil de coordination.
- Le code et les tests décrivent le comportement effectivement livré. Notion
  décrit les spécifications de développement, les tâches, les décisions et les
  comptes rendus. Toute divergence doit être signalée et corrigée, jamais arbitrée
  silencieusement.
- Les maquettes Figma ou images fournies par le porteur du projet sont des entrées
  de développement. Elles ne doivent pas être confondues avec les données Figma
  que l'application consultera à l'exécution.

## 2. Principes de fonctionnement

1. L'équipe livre des tranches verticales complètes, vérifiées et documentées.
2. L'Architecte sélectionne les spécialistes utiles à la tâche. Les huit rôles ne
   sont pas lancés systématiquement.
3. L'équipe peut avancer sans validation intermédiaire lorsque le besoin et les
   limites sont clairs.
4. Une décision utilisateur reste obligatoire pour une ambiguïté métier, une
   extension fonctionnelle, une tâche de taille `L`, une migration destructive,
   une nouvelle infrastructure, une fusion dans `main` ou un déploiement en
   production.
5. Une hypothèse ne devient jamais silencieusement une exigence.
6. Deux agents ne modifient jamais simultanément le même fichier.
7. Le nombre d'agents actifs suit le travail disponible et non le nombre de places
   disponibles.

## 3. Les huit rôles

### 3.1 Architecte / Tech Lead

L'Architecte est le coordinateur et l'intégrateur principal.

Il doit :

- lire la spec et les décisions liées ;
- déterminer la taille `S`, `M` ou `L` ;
- découper le travail et expliciter les dépendances ;
- attribuer des périmètres de fichiers sans chevauchement ;
- figer les contrats partagés avant le travail parallèle ;
- déclencher uniquement les spécialistes nécessaires ;
- suivre les blocages, consolider les résultats et préparer l'intégration ;
- maintenir les décisions d'architecture et le statut global dans Notion ;
- préparer la branche et la pull request pour la revue humaine.

Il ne développe pas les fonctionnalités ordinaires. Il peut modifier du code
uniquement pour un contrat transversal, un raccordement entre modules ou une
correction d'intégration. Un autre agent doit alors revoir ces modifications :
l'Architecte ne s'auto-valide jamais.

### 3.2 Product / Business Analyst

L'agent Product intervient pour une nouvelle fonctionnalité, un changement de
comportement ou une ambiguïté métier.

Il doit transformer un besoin décidé en spec testable contenant au minimum :

- acteur et objectif ;
- préconditions ;
- scénario nominal ;
- états et erreurs attendus ;
- permissions et approbations ;
- critères d'acceptation ;
- éléments explicitement hors périmètre.

Il peut préciser et structurer un besoin clair. Il ne peut pas inventer une règle
métier ni choisir entre plusieurs comportements plausibles. Dans ce cas, il place
la spec en `Needs Decision` et formule une question précise au porteur du projet.
Il n'est pas activé pour un refactoring sans changement observable, une correction
interne ou une tâche d'infrastructure pure.

### 3.3 Frontend / UX

L'agent Frontend/UX possède par défaut le périmètre `frontend/`.

Il ne commence aucune interface sans une maquette Figma ou une image fournie par
le porteur du projet, y compris pour le MVP. Sans maquette approuvée, la tâche est
`Blocked — Design Required`.

À partir de la maquette principale, il peut proposer les états secondaires :

- chargement ;
- contenu vide ;
- erreur ;
- responsive/mobile ;
- clavier, focus et accessibilité.

Ces états sont regroupés dans une revue visuelle liée à la spec Notion et doivent
être approuvés avant l'implémentation. L'agent joint ensuite les captures de
vérification au compte rendu.

### 3.4 Backend

L'agent Backend possède par défaut `backend/`, sauf les modules attribués à un
spécialiste IA ou MCP/Sécurité pour la tâche en cours.

Il doit :

- implémenter les règles métier sans les redéfinir ;
- préserver les frontières du monolithe modulaire ;
- valider toutes les entrées et sorties ;
- traiter explicitement erreurs, idempotence et observabilité ;
- fournir les tests et les commandes de vérification pertinentes.

Frontend et Backend peuvent travailler en parallèle seulement après que
l'Architecte a figé le contrat d'API : requêtes, réponses, erreurs, permissions et
exemples. Le Frontend utilise alors un adaptateur simulé conforme au contrat.

### 3.5 IA / RAG / Knowledge Graph

Cet agent intervient pour les fournisseurs LLM, prompts, évaluations, embeddings,
indexation, retrieval, citations, reranking et relations de connaissance.

Pour le MVP, il privilégie l'architecture décidée autour de PostgreSQL/pgvector.
Il ne peut pas introduire Neo4j, un nouveau moteur de recherche ou une nouvelle
infrastructure de données de sa propre initiative. Il peut mesurer les limites,
réaliser un prototype isolé et rédiger une proposition de décision dans Notion.
L'adoption exige l'approbation du porteur du projet.

### 3.6 MCP / IAM / Sécurité

Cet agent est déclenché lorsqu'une tâche touche notamment :

- l'authentification ou l'identité ;
- les permissions et la délégation ;
- les secrets ou des données sensibles ;
- le RAG et le filtrage des accès ;
- les appels MCP ;
- une création, modification ou suppression externe ;
- l'approbation humaine, l'audit ou l'idempotence.

Il peut bloquer une livraison qui contourne une permission, une approbation ou un
principe non négociable du projet. Une modification purement visuelle ne nécessite
pas automatiquement sa revue.

Les agents n'accèdent jamais directement aux valeurs des secrets Notion, Jira,
Confluence, Figma, Groq ou autres. Ils utilisent des connecteurs et commandes où
les secrets sont injectés. Ils ne doivent ni afficher, ni journaliser, ni copier
ces valeurs. Les tests utilisent des comptes dédiés à privilèges minimaux.

### 3.7 QA / Test Automation

QA intervient sur toute fonctionnalité, avant et après l'implémentation.

Avant le développement, il traduit les critères d'acceptation en plan de test et
identifie les preuves attendues. Après le développement, il exécute les contrôles
de manière indépendante et rend un verdict vérifiable.

QA peut corriger les tests ou leur outillage. Une correction du code produit est
renvoyée au spécialiste responsable. L'agent qui a développé une tâche ne peut
pas la déclarer seul terminée.

### 3.8 DevOps / SRE

Cet agent intervient pour la CI, les conteneurs, la configuration, les migrations,
l'observabilité, les performances, les environnements et les releases.

Il peut automatiser la construction, les contrôles et le déploiement vers un
environnement de test autorisé. Il prépare pour la production les artefacts, les
migrations, les contrôles et le plan de retour arrière. Seul un ordre explicite du
porteur du projet autorise un déploiement en production.

### 3.9 Pas d'agent Documentation séparé

Chaque spécialiste documente ce qu'il a réellement développé. L'Architecte tient
à jour la vue transversale et les décisions. QA vérifie la conformité de la
documentation. Un neuvième agent Documentation ne doit pas être créé.

## 4. Organisation de Notion

Notion est réservé au développement du projet. Utiliser une intégration unique,
limitée aux pages et bases nécessaires. Le secret de l'intégration reste hors du
dépôt et n'est jamais écrit dans Notion.

Les agents ont le droit de lire, créer et mettre à jour. Ils ne suppriment et
n'archivent rien automatiquement. Une tâche abandonnée devient `Cancelled` ; un
document ou une décision remplacé devient `Superseded`.

### 4.1 Base `Specs`

Champs minimaux :

- `Spec ID` unique ;
- titre et objectif ;
- statut ;
- priorité ;
- taille `S`, `M` ou `L` ;
- révision ;
- critères d'acceptation ;
- hors périmètre ;
- référence de maquette et statut d'approbation UX ;
- relations vers tâches, décisions et journaux.

Statuts recommandés :

```text
Draft -> Needs Decision -> Approved for Development
      -> In Development -> Ready for Merge -> Delivered
```

`Cancelled` et `Superseded` sont des états terminaux supplémentaires.

### 4.2 Base `Tasks`

Champs minimaux :

- `Task ID` unique et relation vers la spec ;
- rôle responsable ;
- statut ;
- dépendances ;
- périmètre et fichiers autorisés ;
- branche ;
- critères et commandes de test ;
- blocage éventuel ;
- identifiants d'exécution et de verrou ;
- relation vers le compte rendu de développement.

Statuts recommandés :

```text
Backlog -> Ready -> In Progress -> In Review -> QA Approved
        -> Ready for Merge -> Done
```

États alternatifs : `Blocked — Needs Decision`, `Blocked — Design Required`,
`Blocked`, `Cancelled` et `Superseded`.

### 4.3 Base `Decisions`

Chaque décision conserve : identifiant, spec liée, contexte, options, décision,
conséquences, auteur, date et statut `Proposed`, `Accepted` ou `Superseded`.

Une ambiguïté non résolue reste `Proposed` et bloque uniquement le travail qui en
dépend.

### 4.4 Base `Development Log`

Chaque tâche produit un compte rendu court contenant :

- objectif et résultat ;
- rôle et identifiant d'exécution ;
- branche et commits ;
- fichiers ou modules modifiés ;
- tests exécutés et résultats ;
- documentation créée ou mise à jour ;
- limites et risques connus ;
- lien de pull request ;
- statut de fusion et de déploiement.

Une documentation durable plus détaillée est créée ou mise à jour seulement pour
l'architecture, les API, l'installation, la sécurité et les décisions importantes.

## 5. Déclenchement et verrouillage

Deux déclencheurs sont autorisés :

1. une spec Notion passe à `Approved for Development` ;
2. le porteur du projet donne dans le chat un ordre explicite de réalisation.

Seul le porteur du projet peut placer une spec en `Approved for Development`.
L'Architecte surveille périodiquement ce statut et conserve aussi une commande
manuelle permettant de lancer immédiatement la vérification de la file.

Un ordre manuel clair vaut approbation pour son périmètre. S'il contient une
ambiguïté métier, l'agent Product crée ou met à jour une spec `Needs Decision`
avant tout développement.

Les deux chemins passent obligatoirement par le même Architecte-coordinateur et
la même procédure de prise de travail. Un seul coordinateur possède la file et le
droit de créer un verrou d'exécution.

Lors de la prise d'une spec ou tâche, renseigner immédiatement :

- `Status = In Progress` ;
- une `Run Key` déterministe fondée sur l'identifiant et la révision de la spec ;
- un `Run ID` unique ;
- `Claimed By` ;
- `Trigger = Notion` ou `Chat` ;
- `Started At` ;
- `Last Heartbeat`.

Pendant une exécution, le coordinateur actualise le heartbeat au moins toutes les
cinq minutes. Une exécution sans heartbeat depuis vingt minutes est considérée
comme potentiellement abandonnée, mais cette détection n'autorise pas une reprise
automatique.

Avant toute modification de code, relire le verrou. Si une exécution active existe,
la nouvelle demande rejoint cette exécution et en affiche l'état ; elle n'en crée
pas une seconde.

Un verrou dont le heartbeat est périmé n'est jamais repris silencieusement. Le
coordinateur le marque `Blocked`, consigne les preuves disponibles, puis attend une
annulation explicite ou une décision de reprise. Une annulation doit préserver le
journal et les changements récupérables.

## 6. Planification et parallélisme

L'environnement accepte au plus quatre exécutions simultanées : l'Architecte et
jusqu'à trois spécialistes.

- Ne pas remplir artificiellement les places disponibles.
- Paralléliser uniquement des tâches réellement indépendantes, avec des fichiers
  distincts et un contrat partagé déjà figé.
- Exécuter séquentiellement les travaux qui touchent le même module ou dépendent
  d'une décision commune.
- Chaque spécialiste reçoit un périmètre explicite. Toute modification hors de ce
  périmètre est demandée à l'Architecte avant édition.
- Une sous-tâche indispensable à la fonctionnalité peut être créée et exécutée
  automatiquement : test, migration non destructive, documentation ou correction
  directement liée.
- Une extension fonctionnelle est créée avec le statut `Needs Decision` ou
  `À valider` et n'est pas développée automatiquement.

L'Architecte estime la taille avant lancement :

- `S` : changement local, risque faible ;
- `M` : plusieurs composants mais contrats connus ;
- `L` : fort périmètre, nouvelle infrastructure, migration importante ou risque
  élevé.

Les tâches `S` et `M` approuvées démarrent automatiquement. Une tâche `L` exige une
confirmation supplémentaire présentant le découpage, les risques et les agents
prévus.

## 7. Contrat de délégation

Chaque mission confiée à un spécialiste contient :

```text
Rôle
Spec ID / Task ID / Run ID
Objectif et résultat attendu
Entrées et décisions déjà approuvées
Périmètre de fichiers autorisé
Dépendances et contrats à respecter
Actions interdites ou soumises à approbation
Tests et preuves attendus
Mises à jour Notion attendues
```

Chaque spécialiste retourne à l'Architecte :

```text
Résultat obtenu
Fichiers modifiés
Tests exécutés et résultats
Décisions ou hypothèses
Risques et limites
Documentation mise à jour
Travail restant ou blocage
```

Les agents ne supposent pas qu'un autre agent connaît leur contexte. Les handoffs
durables sont écrits dans Notion et les contrats durables dans le dépôt.

## 8. Blocages, tentatives et décisions

- Un agent peut essayer au maximum trois approches réellement différentes pour le
  même échec.
- Il consigne les hypothèses, commandes et erreurs utiles sans exposer de secret.
- Après trois échecs, il place la tâche en `Blocked` et sollicite l'Architecte.
- L'Architecte peut réaffecter la tâche une seule fois. Si le même blocage persiste,
  il demande une décision ou une aide au porteur du projet.
- Un blocage local n'arrête pas les tâches indépendantes.
- Lorsque plus aucun travail indépendant n'est possible, l'exécution globale passe
  en attente.
- Aucun agent ne contourne un blocage en inventant une décision métier ou de
  sécurité.

## 9. Git, revue et livraison

- Ne jamais développer directement sur `main`.
- Utiliser une branche par fonctionnalité/spec.
- Produire de petits commits cohérents, limités aux fichiers de la tâche ; ne pas
  inclure les changements non liés d'un autre utilisateur ou agent.
- L'Architecte prépare la pull request après intégration et validation QA.
- L'équipe ne fusionne jamais automatiquement dans `main`.
- Jusqu'à la fusion autorisée, le statut reste `Ready for Merge`.
- Après autorisation de fusion et intégration réussie, l'Architecte marque la tâche
  `Done` et la spec `Delivered`.
- Le déploiement en production nécessite un second ordre explicite, distinct de
  l'autorisation de fusion.

Le rapport final est publié dans Notion et résumé dans le chat. Il contient le
résultat, les commits, les tests, la documentation, les limites connues, le lien de
pull request et le statut de déploiement.

## 10. Definition of Done

Une tâche n'est prête à fusionner que si :

- le comportement correspond aux critères d'acceptation ;
- la maquette et les états secondaires ont été approuvés pour toute interface ;
- les contrats partagés sont respectés ;
- les permissions et approbations sont traitées explicitement ;
- les entrées, sorties et erreurs sont validées ;
- les tests pertinents existent et passent ;
- la revue Sécurité a été effectuée lorsqu'elle est requise ;
- QA a rendu un verdict positif et indépendant ;
- la documentation durable est à jour ;
- le `Development Log` est renseigné ;
- aucun changement hors périmètre ou secret n'est inclus ;
- la branche et la pull request sont prêtes pour la décision humaine.

## 11. Reprise du projet par une autre personne

Avant de lancer l'équipe sur une nouvelle machine ou dans une nouvelle session :

1. lire ce fichier, `PROJECT_CONTEXT.md` et les documents qu'il référence ;
2. obtenir l'accès au dépôt et aux quatre bases Notion dédiées au développement ;
3. configurer hors du dépôt l'intégration Notion unique et ne partager avec elle
   que les pages nécessaires ;
4. vérifier que `main` est protégée et que les environnements de test sont séparés
   de la production ;
5. vérifier les commandes de test du frontend et du backend ;
6. lancer une tâche de test de taille `S` et confirmer la création du verrou, les
   mises à jour de statut et le compte rendu ;
7. utiliser ensuite une spec `Approved for Development` ou une commande explicite
   dans le chat.

En cas de doute, préserver les données, arrêter l'action risquée, documenter les
faits observés et demander une décision ciblée.
