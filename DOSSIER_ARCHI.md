# DOSSIER_ARCHI — Plateforme de discussion miniature (version 2)

**Bachelor 3 Ynov Montpellier — Conception et architecture des données, 2026-2027**  
**Documents sources :** « TP1 – Architecture des données Discord.pdf » (7 pages, rendu initial) ; résultats des missions 0 à 6 du TP2 dans `MESURES.md` ; scripts SQL, CQL et Python du projet.

> **Traçabilité importante.** Le PDF réellement remis au TP1 contient les sections 0, 1.a à 1.e, 2.a à 2.c, 3.a à 3.d et 4.a. La section **1.d n'est pas rédigée**, et la page 7 s'arrête au titre **4.b**, sans contenu. Les sections 4.c, 4.d, 4.e et 4.f, notamment les cinq hypothèses falsifiables demandées, **n'apparaissent pas dans ce PDF**. Elles sont précisées ici au Jour 2, sans les présenter comme du texte écrit la veille. Les objectifs du TP1 ne doivent pas être confondus avec des mesures de production.

## 0. Ce que j'ai retenu de Discord (TP1, page 1)

Discord a dû stocker et relire un volume croissant de messages. MongoDB s'est mis à produire des lectures moins régulières quand le volume augmentait. Discord a ensuite utilisé Cassandra puis ScyllaDB. Trois repères étaient retenus dans mon TP1 : **100 millions de messages par jour**, environ **50 % de lectures et 50 % d'écritures**, et un seuil d'attention de **100 Mo par partition Cassandra**. Ces chiffres décrivent l'historique étudié, pas les mesures de ma miniature.

## 1. Ce que la plateforme doit garantir

### 1.a. Acteurs et données (TP1, page 1)

Les acteurs sont les utilisateurs, les modérateurs et les propriétaires de serveur. Les objets sont les utilisateurs, serveurs, salons, messages, pièces jointes, amitiés et présences. Un utilisateur peut rejoindre un serveur et y écrire selon ses droits. Un *serveur* désigne ici une communauté Discord, pas une machine informatique.

### 1.b. Règles retenues (TP1, pages 1-2)

| Garantie par la base | Garantie par du code / un trigger | Hors du stockage relationnel durable |
|---|---|---|
| Email unique | Vérifier l'appartenance avant d'écrire | Expiration de la présence après 5 min |
| Nom de salon unique dans un serveur | Interdire les messages dans un salon vocal | Présence éphémère dans Redis |
| Une amitié enregistrée une seule fois | Vérifier le propriétaire du serveur | Fichiers binaires stockés séparément si nécessaire |
| Rôle parmi propriétaire, modérateur et membre | Contrôler le droit de supprimer un message | Cache éventuel, sans remplacer la vérité SQL |

### 1.c. MCD et choix (TP1, page 2)

Le MCD original lie **utilisateur, appartenance, serveur, salon, message, pièce jointe, amitié et activité par jour** ; il est repris sous forme de diagramme Mermaid dans `mcd.md`. Les choix initiaux étaient : rôle porté par l'appartenance ; propriétaire également membre ; amitié enregistrée une seule fois ; pièce jointe séparée du message ; message conservé comme entité métier.

### 1.d. Modèle physique réalisé au TP2 — ajout du Jour 2

Cette partie était vide dans le PDF du TP1. Voici le **schéma effectivement créé et testé** par `sql/01_schema.sql` :

- `app.utilisateur(id, pseudo, email, cree_le)` : PK et unicité des identifiants, pseudo et email.
- `app.serveur(id, nom, proprietaire_id, cree_le, nb_membres)` : FK vers un utilisateur, compteur de membres maintenu par trigger depuis la Mission 2.
- `app.salon(id, serveur_id, nom, type, cree_le)` : FK vers serveur ; nom unique par serveur ; type `texte` ou `vocal`.
- `app.membre(utilisateur_id, serveur_id, role, rejoint_le)` : clé composée ; rôles limités aux trois valeurs prévues.
- `app.message(id BIGINT, salon_id, auteur_id, contenu, envoye_le, modifie_le, pieces_jointes JSONB)` : FK, dates cohérentes, contrôle d'appartenance et de type de salon par trigger.
- `app.amitie(utilisateur_a, utilisateur_b, depuis)` : clé composée et contrainte `a < b`.
- `app.presence(utilisateur_id, vu_le)` : comparaison PostgreSQL pour les benchmarks, non destinée à être la source métier principale de présence dans l'architecture cible.

L'index `(salon_id, id DESC)` répond aux 50 derniers messages par salon ; les index sur les membres et les deux extrémités de l'amitié servent les jointures. Les 8 tests de contraintes de la Mission 1 ont réussi.

**Écarts à reconnaître :** le TP1 prévoyait une entité `PIECE_JOINTE` séparée, tandis que le SQL testé stocke un JSONB dans `message`. Le TP1 disait aussi que le propriétaire devait être un membre sans information redondante ; le schéma testé comporte **`serveur.proprietaire_id` et un rôle `proprietaire` dans `membre`**, rendus cohérents par index et triggers. Les règles de concurrence et la gestion des vrais fichiers ne sont pas démontrées par ce TP.

### 1.e. Cinq questions laissées ouvertes (TP1, page 2)

Plusieurs pièces jointes par message ? Un message peut-il contenir seulement une image ? Que devient le serveur si son propriétaire part ? Les messages supprimés doivent-ils être conservés ? Les suggestions doivent-elles se mettre à jour immédiatement ? Ces réponses pourraient modifier les cardinalités, la politique de suppression et le choix des caches ; elles n'ont pas été données par un client dans ce TP.

## 2. Accès, objectifs et volume

### 2.a. Accès prévus au TP1 (page 3)

| Accès | Fréquence supposée | Latence visée | Cohérence |
|---|---:|---:|---|
| Envoyer un message | 10/s | 80 ms | Stricte |
| Lire les 50 derniers messages | 30/s | 80 ms | Stricte |
| Vérifier les droits | 10/s | 20 ms | Stricte |
| Voir les membres en ligne | 10/s | 80 ms | Éphémère |
| Suggérer des serveurs | 3/s | 200 ms | Retard accepté |
| Calculer les statistiques | 1/jour | Pas urgent | Retard accepté |
| Supprimer un message | Fréquence non quantifiée (« à la seconde » dans le TP1) | 80 ms | Stricte |
| Rechercher un message | 1/s | 300 ms | Retard accepté |

Ce sont des **objectifs estimés**, pas des charges qui ont été reproduites. Les benchmarks Python du Jour 2 sont séquentiels et mesurent les fonctions locales, pas une API complète à 30 requêtes par seconde.

### 2.b. Calculs initiaux (TP1, page 3)

- 100 000 000 / 86 400 = **environ 1 157 messages/s** ; pic supposé x3 = **environ 3 472 messages/s**.
- 100 000 000 messages x 300 octets = **30 Go** ; à ce rythme, **10,95 To/an**.
- 30 Go de données + 4 Go d'index théorique = **34 Go**, supérieur aux **16 Go de RAM supposés** pour l'exemple historique.
- Avec 12 nœuds de 1 To et trois copies : environ **4 To logiques compressés** (ordre de grandeur, non volume exact utile).

### 2.c. Dénormalisations envisagées (TP1, page 4) et mesurées

Le TP1 proposait éventuellement un cache des derniers messages, des statistiques calculées chaque jour et des suggestions conservées temporairement, tout en soulignant le risque de données périmées. Au TP2, **seules** deux optimisations relationnelles ont été testées : la vue matérialisée `app.activite_serveur_jour` et le compteur `nb_membres`. La vue a donné **p50 0,15 ms** contre **3,11 ms** pour le SQL normalisé lors du benchmark final B4. Elle nécessite cependant un rafraîchissement. Aucun cache Redis des 50 derniers messages n'a été benchmarké.

## 3. Choix du stockage des messages

### 3.a-3.b. Raisonnement du TP1 (page 4)

MongoDB peut devenir irrégulier lorsque données et index dépassent la mémoire disponible et que les lectures demandent des pages sur disque. PostgreSQL gère efficacement les relations et les messages de cette miniature. Cassandra est intéressant à grande échelle, mais impose des requêtes adaptées au partitionnement. Redis sert de cache / présence, pas de stockage unique de l'historique.

### 3.c. Partitions Cassandra (TP1, page 5)

Pour un salon hypothétique à **10 millions de messages/an**, avec **300 octets/message** :

| Option initiale | Clé de partition | Taille calculée |
|---|---|---:|
| A | Salon | 3 000 Mo |
| B | Salon + fenêtre de 10 jours | environ 82 Mo |
| C | Salon + jour | environ 8,2 Mo |

**Préférence exprimée au TP1 : option B**, compromis entre taille des partitions et nombre de fenêtres à lire. Pour un petit salon à 1 000 messages/an, 50 messages peuvent nécessiter environ 2 à 3 fenêtres de dix jours (hypothèse de répartition régulière). Au TP2, le salon clairsemé a nécessité **26 fenêtres** dans la lecture naïve contre **1** en consultant la liste des fenêtres non vides. Les deux situations ne représentent pas le même rythme de publication : la seconde mesure **confirme le risque des fenêtres vides**, mais ne valide pas la taille théorique de 82 Mo à 10 millions de messages.

### 3.d. Risques (TP1, page 5) et test Cassandra

Le TP1 identifiait les `NULL` inutiles, les millions de suppressions, les salons très sollicités et les pauses mémoire de Cassandra. La Mission 4 a réellement reproduit un échec **`READ_TOO_MANY_TOMBSTONES`** après 119 999 suppressions, puis deux stratégies expérimentales dans le `RUNBOOK_tombstones.md`. Le TP n'a pas mesuré les pauses JVM ou la contention d'un cluster Cassandra multi-nœud.

## 4. Architecture : passage du TP1 au TP2

### 4.a. Répartition effectivement proposée au TP1 (pages 5-6)

Le choix annoncé au Jour 1 était **PostgreSQL + Redis** : PostgreSQL pour comptes, serveurs, membres, salons, messages, contrôles de droits, amitiés, suggestions et statistiques ; Redis pour une présence qui expire ; fichiers binaires stockés hors des tables SQL. PostgreSQL est la source de vérité **durable** et Redis la source de l'état **éphémère** de présence. Le TP1 prévoyait un calcul nocturne des statistiques et des suggestions calculées en SQL.

### 4.b. Schéma d'architecture — complété au Jour 2

Le titre 4.b figure dans le PDF, mais son contenu est vide. Le schéma cible, **nouvellement explicité**, se trouve dans `architecture.md`. Il distingue l'architecture minimale de production (PostgreSQL + Redis) des moteurs uniquement utilisés pour comparer les performances au TP2 (MongoDB, Cassandra, Neo4j).

### 4.c. Trois décisions d'architecture — formulées au Jour 2 depuis le choix 4.a

**Décision 1 — PostgreSQL pour les messages et données métier : maintenue.** L'idée apparaît dès le tableau 4.a du TP1. Les B1 du benchmark final placent PostgreSQL devant MongoDB et Cassandra sur les trois salons : p95 **0,16 ms** (chaud), **0,14 ms** (moyen) et **0,16 ms** (clairsemé). L'index `(salon_id, id DESC)` suffit dans cette expérience locale. Le passage à un stockage distribué n'est pas démontré nécessaire pour 300 000 messages.

**Décision 2 — Droits et rôles contrôlés dans PostgreSQL : maintenue, réalisation différente.** Le TP1 voulait vérifier l'appartenance avant l'envoi et un seul propriétaire par serveur. Les tests SQL refusent le non-membre et l'envoi dans un salon vocal. Le schéma réalisé duplique la propriété via `proprietaire_id` et le rôle propriétaire, mais des triggers et des contraintes contrôlent leur concordance. L'exclusion d'un membre pendant un envoi simultané **n'a pas** fait l'objet d'un test concurrent.

**Décision 3 — Redis pour la présence : maintenue, avec réserve.** Le TP1 demandait une expiration au bout de cinq minutes. Redis a démontré son TTL sur une clé de test à **2 s**, et les écritures de présence B2a sont plus rapides que SQL (**p50 0,13 contre 0,26 ms**). Pour compter les présents dans un serveur, PostgreSQL gagne en revanche (**p50 0,21 contre 1,13 ms**). Redis ne doit pas devenir une source de vérité pour les droits ou les messages ; le cache de messages est **non activé faute de mesure directe**.

> Ces trois décisions sont une **formalisation du Jour 2** des choix visibles en 4.a du PDF. Elles ne sont **pas présentées comme des ADR rédigés à la section 4.c du TP1**, laquelle n'existe pas dans le fichier remis.

### 4.d. Risque de divergence — analyse ajoutée au Jour 2

Si un message est supprimé de PostgreSQL mais reste dans un éventuel cache Redis, un utilisateur peut voir du contenu supprimé. La réponse envisagée est : cache non activé par défaut ; sinon invalidation fiable après `COMMIT`, TTL court et possibilité de relire PostgreSQL. En cas de besoin de cohérence immédiate, il faut éviter de servir la copie sans vérification. Ce scénario **n'a pas été testé comme panne de cache** au TP2.

### 4.e. Version minimale avec deux moteurs — précisée au Jour 2

**On conserve PostgreSQL et Redis**, conformément au choix déjà écrit dans le TP1 4.a. PostgreSQL garde les données durables et leurs contraintes ; Redis ne garde que les présences temporaires. La vue matérialisée des statistiques reste dans PostgreSQL. MongoDB, Cassandra et Neo4j ne sont utilisés ici que pour des tests comparatifs ; ils ajoutent de l'exploitation sans gain démontré pour nos requêtes à cette échelle. Un espace de fichiers n'est pas un troisième moteur de base de données.

### 4.f. Tableau des hypothèses — reformulé après les mesures (traçabilité)

**Avertissement :** le PDF du TP1 ne contient **aucun tableau 4.f de cinq hypothèses chiffrées**. Les lignes suivantes reformulent **cinq attentes réellement déductibles de ses pages 3 à 6**, avec des valeurs originales quand elles existent. Elles ne doivent pas être présentées comme cinq prédictions quantitatives écrites avant les tests.

| N° | Attente issue du TP1 | Valeur visée ou calculée dans le TP1 | Observation réelle au TP2 | Verdict et mécanisme |
|---|---|---|---|---|
| 1 | Afficher vite les 50 derniers messages | **80 ms** de latence visée (p.3), sans percentile précisé | PostgreSQL B1 p95 **0,16 / 0,14 / 0,16 ms** selon le salon | **Soutenu en lecture locale**, indécidable pour l'API sous 30 lectures/s : un index `(salon_id, id DESC)` rend le tri rapide sur la miniature. |
| 2 | Contrôler les droits rapidement et strictement | **20 ms** visés (p.3) | R2 SQL **0,292 ms** à l'exécution relevée ; tests d'intégrité réussis | **Soutenu sur le scénario testé**, non vérifié en p95 ni sous exclusion concurrente ; recherches indexées et trigger. |
| 3 | Expiration automatique de la présence Redis | **5 min = 300 s** (p.2) | TTL `EX 2` a expiré après **2,4 s** ; clés opérationnelles configurées `EX 300` | **Mécanisme confirmé**, expiration à exactement 300 s non chronométrée. PostgreSQL exigerait un filtrage sur `last_seen_at` et une purge optionnelle. |
| 4 | Clé Cassandra `(salon, 10 jours)` pour limiter les partitions | **≈ 82 Mo/partition** dans le scénario théorique 10 M/an (p.5) | 15 965 partitions pour 300 k messages ; salon clairsemé : **26** fenêtres naïves / **1** non vide | **Indécidable sur les 82 Mo à grande échelle** ; coût des fenêtres vides réellement observé. |
| 5 | Pré-calcul des statistiques pour éviter le recalcul à chaque lecture | **Calcul quotidien**, pas de facteur de vitesse annoncé (p.4 et p.6) | B4 p95 SQL normalisé **3,98 ms** ; vue matérialisée **0,19 ms** | **Gain local confirmé** (p50 environ **20,7×**) ; coût du rafraîchissement et obsolescence non chiffrés sur charge réelle. |

Cette mise au clair répond à l'analyse demandée au TP2 sans inventer de « facteur prédit x2/x3 » absent du rendu initial. Pour une comparaison strictement conforme à la consigne « cinq hypothèses de 4.f d'hier », il aurait fallu disposer d'une section 4.f réellement rédigée et datée **avant** les mesures ; elle manque dans le PDF fourni.

## 5. Verdict architectural fondé sur les mesures (Mission 6)

### Bilan de B1 à B4

- **Messages B1 :** PostgreSQL est le plus rapide dans les trois salons. Sur le salon clairsemé, Cassandra naïf prend **8,29 ms p50** ; l'optimisation fenêtres non vides réduit à **0,85 ms** mais PostgreSQL reste à **0,14 ms**.
- **Présence B2a/B2b :** Redis gagne sur l'écriture, mais perd sur le comptage des personnes en ligne dans un serveur. Cela tient aux accès nécessaires au comptage dans le modèle de test Redis.
- **Suggestions B3/B3 bis :** PostgreSQL p50 **0,14 / 0,31 ms**, Neo4j **0,97 / 0,92 ms**. Aucun avantage Neo4j pour ce petit graphe et ces parcours simples. Cela ne préjuge pas des graphes profonds à grande échelle.
- **Activité B4 :** la vue matérialisée PostgreSQL p50 **0,15 ms**, SQL normalisé **3,11 ms**, MongoDB agrégé **1,77 ms** ; égalité de résultats vérifiée sur **31 jours / 1 928 messages**.
- **Incident Cassandra :** après 119 999 suppressions individuelles, `READ_TOO_MANY_TOMBSTONES`. La purge locale et la suppression complète de partition ne sont pas des procédures interchangeables ; voir le runbook.

### Pourquoi regarder le p95 et échauffer les requêtes ?

Le p95 représente une valeur sous laquelle passent environ 95 % des lectures : il révèle les requêtes lentes que la moyenne peut masquer. Le benchmark a exécuté **10 appels d'échauffement** par cas avant de mesurer, afin de limiter le coût des connexions initiales et des caches froids. Cela signifie aussi que ses résultats sont principalement des **mesures à chaud**.

### Trois limites capables de changer le verdict

1. **Volume :** 300 000 messages et 5 000 utilisateurs, sans saturation mémoire ; un système massif aurait d'autres besoins de partitionnement.
2. **Concurrence :** requêtes séquentielles, sans 30 lecteurs/s réels, sans écritures simultanées ni pannes de nœuds ; le p95 observé n'est pas le p95 d'une API réelle.
3. **Réseau et ressources :** les moteurs partagent Docker Desktop sur un Mac, avec accès local et sans cluster multi-nœud représentatif. Le réseau, l'I/O et la réplication pourraient changer le résultat.

### Signaux mesurables qui justifieraient une révision

| Besoin futur | Signal à tester avant d'ajouter un moteur | Non testé ici |
|---|---|---|
| Messages en forte charge | p95 **API** des 50 derniers messages au-delà de l'objectif initial **80 ms**, après indexation et tuning, de manière répétée | Plusieurs millions de messages et forte concurrence |
| Suggestions complexes | parcours relationnels qui dépassent l'objectif initial **200 ms** sous charge, et meilleure solution démontrée par comparaison équivalente | Graphes profonds et grosses communautés |
| Recherche texte | recherche qui dépasse l'objectif initial **300 ms**, après index PostgreSQL adapté | Moteur de recherche spécialisé et pertinence |
| Cache Redis de messages | gain p95 prouvé pour les **mêmes 50 messages**, avec stratégie de cohérence et taux de succès réaliste | Aucune comparaison Redis contre SQL pour B1 |
| Droit d'écriture | latence API dépassant **20 ms** ou incohérence sous exclusion simultanée | Test concurrent de transaction et verrouillage |

**Si le budget ne permet que deux moteurs : PostgreSQL + Redis.** Ce choix **ne change pas** par rapport au tableau 4.a du TP1. PostgreSQL couvre les règles et les données durables ; Redis apporte un TTL natif pour les états temporaires. Les autres moteurs resteraient des candidats à reconsidérer uniquement si de nouvelles mesures sous charge démontrent un besoin.

## 6. Sources et preuves

- TP1 original : `TP1 – Architecture des données Discord.pdf`, 7 pages, notamment p. 3 (objectifs), p. 5 (partitions) et p. 6 (choix des moteurs).
- Mesures : `MESURES.md` (Mesures 0 à 8) et logs `mission2_resultats.txt`, `mission3_bench.txt`, `mission5_bench.txt`, `mission6_bench.txt`.
- Code : `sql/01_schema.sql`, `sql/03_requetes.sql`, `sql/04_tests_mission1.sql`, `cql/01_schema.cql`, `bench/load_nosql.py`, `bench/bench.py`.
- Incident : `RUNBOOK_tombstones.md` et `mission4_*`.
- Sources Discord étudiées au TP1 : articles techniques Discord *How Discord Stores Billions of Messages* (2017) et *How Discord Stores Trillions of Messages* (2023), via le dossier documentaire fourni au cours.
